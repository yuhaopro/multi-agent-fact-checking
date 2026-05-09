import csv
import logging
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared import graph_client, kafka_client
from shared.models import Media, PostQueryRequest
from services import eval_store

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_TRUTH_LABELS = {"supported", "refuted", "NEI"}
_CORPUS_PATH = Path(__file__).parent.parent.parent / "mocheg" / "test" / "Corpus2.csv"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_mocheg_claims(path: Path) -> list[dict]:
    """Loads unique claims from a MOCHEG Corpus2.csv file."""
    seen: set[str] = set()
    claims: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row.get("claim_id", "")
            if not cid or cid in seen:
                continue
            claim = row.get("Claim", "").strip()
            truth = row.get("cleaned_truthfulness", "").strip()
            if not claim or not truth:
                continue
            seen.add(cid)
            claims.append({
                "claim_id": cid,
                "claim_text": claim,
                "snopes_url": row.get("Snopes URL", ""),
                "truth_label": truth,
            })
    return claims


def _create_and_queue_claim(
    claim_text: str,
    snopes_url: str,
    dataset_claim_id: str,
    truth_label: str,
    image_urls: list[str],
    producer,
) -> str:
    """Creates a Post node in Memgraph, optionally registers in eval_store, and queues
    it to the query-generation stage of the pipeline."""
    now = _now()
    post_id = str(uuid.uuid4())

    graph_client.upsert_post({
        "id": post_id,
        "url": snopes_url,
        "title": "",
        "content": claim_text,
        "status": "TBD",
        "justification": "",
        "created_at": now,
        "updated_at": now,
    })

    if truth_label:
        eval_store.register(
            post_id,
            dataset_claim_id or post_id,
            truth_label,
            claim_text,
            snopes_url,
        )

    producer.send(
        kafka_client.POST_QUERY_TOPIC,
        value=PostQueryRequest(
            post_id=post_id,
            url=snopes_url,
            content=claim_text,
        ).model_dump_json().encode(),
    )

    for image_url in image_urls:
        media = Media(post_id=post_id, url=image_url, type="IMAGE")
        media_params = {
            "id": media.id,
            "url": media.url,
            "type": media.type,
            "status": "PENDING",
            "created_at": now,
            "updated_at": now,
        }
        try:
            graph_client.create_and_connect_media(media_params, post_id)
            producer.send(
                kafka_client.MEDIA_CREATION_TOPIC,
                value=media.model_dump_json().encode(),
            )
        except Exception as e:
            logger.warning(f"Failed to create/queue media {image_url!r}: {e}")

    return post_id


# ─── Request / Response models ────────────────────────────────────────────────

class EvalSubmitRequest(BaseModel):
    claim_text: str
    dataset_claim_id: str = ""        # optional — auto-generated if omitted
    snopes_url: str = ""              # optional reference URL
    truth_label: str = ""             # supported | refuted | NEI — omit to skip accuracy tracking
    image_urls: list[str] = []


class EvalSubmitResponse(BaseModel):
    post_id: str
    dataset_claim_id: str
    message: str


class BatchSubmitRequest(BaseModel):
    sample_size: int = 10
    seed: int = 42
    claim_ids: list[str] = []         # if non-empty, use these IDs instead of random sample


class BatchSubmitResponse(BaseModel):
    submitted: int
    post_ids: list[str]
    message: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/eval/submit", response_model=EvalSubmitResponse, status_code=202)
async def submit_eval(req: EvalSubmitRequest) -> EvalSubmitResponse:
    """Accepts a claim, injects it directly into the fact-check pipeline (skipping
    URL scraping). If truth_label is provided it is registered for accuracy tracking;
    otherwise the verdict is still produced but not compared to ground truth."""
    if req.truth_label and req.truth_label not in _VALID_TRUTH_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"truth_label must be one of {_VALID_TRUTH_LABELS}",
        )

    producer = kafka_client.get_producer()
    try:
        post_id = _create_and_queue_claim(
            claim_text=req.claim_text,
            snopes_url=req.snopes_url,
            dataset_claim_id=req.dataset_claim_id,
            truth_label=req.truth_label,
            image_urls=req.image_urls,
            producer=producer,
        )
        producer.flush()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue claim: {e}")

    logger.info(
        f"Eval: submitted claim as post {post_id} "
        f"(dataset_claim_id={req.dataset_claim_id!r}, truth_label={req.truth_label!r})"
    )
    return EvalSubmitResponse(
        post_id=post_id,
        dataset_claim_id=req.dataset_claim_id or post_id,
        message="Claim accepted and queued for fact-checking",
    )


@router.get("/eval/mocheg/claims")
async def get_mocheg_claims(sample: int = 10, seed: int = 42) -> list[dict]:
    """Returns a random sample of claims from the MOCHEG test corpus for preview."""
    if not _CORPUS_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="MOCHEG corpus not found at mocheg/test/Corpus2.csv",
        )
    all_claims = _load_mocheg_claims(_CORPUS_PATH)
    n = min(max(1, sample), len(all_claims))
    return random.Random(seed).sample(all_claims, n)


@router.post("/eval/batch", response_model=BatchSubmitResponse, status_code=202)
async def submit_batch(req: BatchSubmitRequest) -> BatchSubmitResponse:
    """Loads claims from the MOCHEG test corpus and submits them to the pipeline in bulk.
    Each claim skips URL scraping and enters at the query-generation stage."""
    if not _CORPUS_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="MOCHEG corpus not found at mocheg/test/Corpus2.csv",
        )

    all_claims = _load_mocheg_claims(_CORPUS_PATH)
    if not all_claims:
        raise HTTPException(status_code=500, detail="No claims loaded from MOCHEG corpus")

    if req.claim_ids:
        requested = {str(cid) for cid in req.claim_ids}
        sample = [c for c in all_claims if c["claim_id"] in requested]
    else:
        n = min(max(1, req.sample_size), len(all_claims))
        sample = random.Random(req.seed).sample(all_claims, n)

    producer = kafka_client.get_producer()
    post_ids: list[str] = []

    for claim in sample:
        try:
            post_id = _create_and_queue_claim(
                claim_text=claim["claim_text"],
                snopes_url=claim["snopes_url"],
                dataset_claim_id=claim["claim_id"],
                truth_label=claim["truth_label"],
                image_urls=[],
                producer=producer,
            )
            post_ids.append(post_id)
        except Exception as e:
            logger.warning(f"Failed to queue MOCHEG claim {claim['claim_id']}: {e}")

    producer.flush()
    logger.info(f"Batch: queued {len(post_ids)}/{len(sample)} MOCHEG claims")
    return BatchSubmitResponse(
        submitted=len(post_ids),
        post_ids=post_ids,
        message=f"{len(post_ids)} MOCHEG claims queued for fact-checking",
    )


@router.get("/eval/results")
async def get_results() -> dict:
    """Returns current evaluation accuracy metrics against registered ground-truth labels."""
    return eval_store.get_results()
