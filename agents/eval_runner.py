#!/usr/bin/env python3
"""Evaluation runner: reads claims from the MOCHEG test set, submits them to the
fact-checking pipeline, waits for all verdicts, then writes a JSON report.

Usage:
    uv run python eval_runner.py                          # random sample via full pipeline
    uv run python eval_runner.py --claim-ids 9484 8033   # specific claim IDs via full pipeline
    uv run python eval_runner.py --basic                  # basic agent (gpt-4o-mini + images)
    uv run python eval_runner.py --basic --claim-ids 9484 8033
"""
import argparse
import csv
import json
import os
import random
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from shared import graph_client, kafka_client, storage_client  # noqa: E402 — must come after load_dotenv
from shared.models import BasicClaimRequest, BasicVerdict  # noqa: E402

CORPUS_PATH = f"mocheg/test/Corpus2.csv"
IMG_QRELS_PATH = f"mocheg/test/img_evidence_qrels.csv"
IMAGES_DIR = f"mocheg/test/images"
API_URL = os.getenv("EVAL_API_URL", "http://localhost:8081/api/v1/eval/submit")
RESULTS_URL = API_URL.replace("/eval/submit", "/eval/results")
SAMPLE_SIZE = 10
RANDOM_SEED = 43
POLL_INTERVAL = 10   # seconds between result polls
POLL_TIMEOUT  = 4800  # seconds before giving up

_LABEL_MAP = {"supported": "VERIFIED", "refuted": "REFUTED", "NEI": "NEI"}


def load_unique_claims(path: Path) -> list[dict]:
    """Returns one row per unique claim_id, skipping rows with empty claim text."""
    seen: set[str] = set()
    claims: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row["claim_id"]
            if cid not in seen and row["Claim"].strip() and row["cleaned_truthfulness"].strip():
                seen.add(cid)
                claims.append(row)
    return claims


def load_image_qrels(path: Path) -> dict[str, list[str]]:
    """Returns {claim_id: [image_filename, ...]} for RELEVANCY=1 entries only."""
    if not path.exists():
        return {}
    qrels: dict[str, list[str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("RELEVANCY") == "1":
                qrels.setdefault(row["TOPIC"], []).append(row["DOCUMENT#"])
    return qrels


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read())


# ─── MinIO image upload ───────────────────────────────────────────────────────

def upload_claim_images(claim_id: str, filenames: list[str]) -> list[str]:
    """Uploads MOCHEG images for a claim to MinIO and returns their public URLs."""
    urls: list[str] = []
    for filename in filenames:
        local_path = f"{IMAGES_DIR}/{filename}"
        if not Path(local_path).exists():
            print(f"    WARN image not found on disk, skipping: {filename}")
            continue
        try:
            url = storage_client.upload_file(str(local_path), f"mocheg/{claim_id}/{filename}")
            urls.append(url)
        except Exception as e:
            print(f"    WARN failed to upload {filename}: {e}")
    return urls


# ─── Pipeline polling ─────────────────────────────────────────────────────────

def poll_until_complete(submitted_post_ids: set[str]) -> dict:
    """Polls the results endpoint until all submitted claims in this run have a verdict."""
    total = len(submitted_post_ids)
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            all_results = get_json(RESULTS_URL)
            records = all_results.get("records", [])
            run_records = [r for r in records if r["post_id"] in submitted_post_ids]
            completed = sum(1 for r in run_records if r.get("system_verdict") is not None)
            print(f"  [{completed}/{total} completed]", end="\r", flush=True)
            if completed >= total:
                print()
                return _build_run_results(run_records)
        except Exception as e:
            print(f"  Poll error: {e}")
        time.sleep(POLL_INTERVAL)
    print(f"\nTimeout after {POLL_TIMEOUT}s — writing partial results.")
    try:
        all_results = get_json(RESULTS_URL)
        run_records = [r for r in all_results.get("records", []) if r["post_id"] in submitted_post_ids]
        return _build_run_results(run_records)
    except Exception:
        return {}


def _build_run_results(run_records: list[dict]) -> dict:
    """Builds a results dict scoped to the current run's records."""
    completed = sum(1 for r in run_records if r.get("system_verdict") is not None)
    correct = sum(1 for r in run_records if r.get("correct"))
    per_label: dict[str, dict] = {}
    for r in run_records:
        if r.get("system_verdict") is not None:
            lbl = r["truth_label"]
            if lbl not in per_label:
                per_label[lbl] = {"total": 0, "correct": 0}
            per_label[lbl]["total"] += 1
            if r.get("correct"):
                per_label[lbl]["correct"] += 1
    return {
        "total_submitted": len(run_records),
        "completed": completed,
        "correct": correct,
        "accuracy": correct / completed if completed > 0 else 0.0,
        "avg_latency_seconds": sum(r.get("latency_seconds") or 0 for r in run_records if r.get("system_verdict")) / completed if completed > 0 else 0.0,
        "avg_cost": sum(sum((r.get("costs") or {}).values()) for r in run_records if r.get("system_verdict")) / completed if completed > 0 else 0.0,
        "per_label": per_label,
        "records": run_records,
    }


# ─── Memgraph artifact enrichment ────────────────────────────────────────────

def fetch_artifact(post_id: str) -> dict:
    """Fetches all Memgraph data for a post and returns it as a dict."""
    try:
        post = graph_client.get_post_node(post_id)
    except Exception as e:
        return {"error": str(e)}
    try:
        queries = graph_client.get_all_evidences_for_post(post_id)
    except Exception:
        queries = []
    try:
        media = graph_client.get_media_for_post(post_id)
    except Exception:
        media = []
    return {"post": post, "queries": queries, "media": media}


def enrich_with_artifacts(records: list[dict]) -> None:
    """Adds an 'artifact' field to each record with the full Memgraph dump."""
    for record in records:
        post_id = record.get("post_id")
        record["artifact"] = fetch_artifact(post_id) if post_id else None




# ─── Basic agent evaluation (via Kafka) ──────────────────────────────────────

_BASIC_POLL_INTERVAL = 10   # seconds between verdict polls
_BASIC_POLL_TIMEOUT  = 3600  # seconds before giving up


def submit_basic_claims(
    sample: list[dict],
    image_qrels: dict[str, list[str]],
) -> dict[str, dict]:
    """Publishes BasicClaimRequest messages to Kafka.

    Returns a post_id → {"row": ..., "submitted_at": float} mapping.
    """
    producer = kafka_client.get_producer()
    submitted: dict[str, dict] = {}  # post_id → {row, submitted_at}

    for row in sample:
        # Resolve absolute paths for local MOCHEG images
        image_filenames = image_qrels.get(row["claim_id"], [])
        image_paths: list[str] = []
        for fn in image_filenames:
            local = Path(IMAGES_DIR) / fn
            if local.exists():
                image_paths.append(str(local))
            else:
                print(f"WARN image not found locally, skipping: {fn}")

        post_id = str(uuid.uuid4())
        req = BasicClaimRequest(
            post_id=post_id,
            claim_text=row["Claim"],
            dataset_claim_id=row["claim_id"],
            truth_label=row["cleaned_truthfulness"],
            snopes_url=row["Snopes URL"],
            image_paths=image_paths,
        )
        try:
            producer.send(
                kafka_client.BASIC_CLAIM_TOPIC,
                value=req.model_dump_json().encode(),
            )
            submitted[post_id] = {"row": row, "submitted_at": time.time()}
            print(
                f"  queued claim_id={row['claim_id']:>6}  "
                f"images={len(image_paths)}  post_id={post_id}"
            )
        except Exception as e:
            print(f"  ERR claim_id={row['claim_id']:>6}  error={e}")

    producer.flush()
    return submitted


def poll_basic_verdicts(submitted: dict[str, dict], image_qrels: dict[str, list[str]]) -> dict:
    """Consumes BASIC_VERDICT_TOPIC until all submitted post_ids have a verdict."""
    from kafka import KafkaConsumer

    total = len(submitted)
    if total == 0:
        return {}

    # Unique group so we always read from the current offset position.
    # Subscribe before publishing so we don't miss any fast responses.
    group_id = f"eval-basic-{uuid.uuid4()}"
    consumer = KafkaConsumer(
        kafka_client.BASIC_VERDICT_TOPIC,
        bootstrap_servers=kafka_client.get_brokers(),
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda v: v,
        session_timeout_ms=30_000,
        heartbeat_interval_ms=5_000,
        consumer_timeout_ms=_BASIC_POLL_INTERVAL * 1000,
    )

    verdicts: dict[str, BasicVerdict] = {}
    latencies: dict[str, float] = {}
    t_start = time.time()

    print(f"Waiting for basic_agent to return {total} verdict(s)...")
    while len(verdicts) < total:
        if time.time() - t_start > _BASIC_POLL_TIMEOUT:
            print(f"\nTimeout after {_BASIC_POLL_TIMEOUT}s — writing partial results.")
            break

        for msg in consumer:
            if msg.value is None:
                continue
            try:
                bv = BasicVerdict.model_validate_json(msg.value)
            except Exception:
                continue
            if bv.post_id in submitted and bv.post_id not in verdicts:
                latency = bv.latency_seconds
                verdicts[bv.post_id] = bv
                latencies[bv.post_id] = latency
                row = submitted[bv.post_id]["row"]
                truth_label = row["cleaned_truthfulness"]
                expected = _LABEL_MAP.get(truth_label, "NEI")
                correct = bv.verdict == expected
                total_k_cost = sum(bv.costs.values())
                print(
                    f"  claim_id={row['claim_id']:>6}  "
                    f"truth={truth_label:<10}  "
                    f"verdict={bv.verdict:<10}  "
                    f"{'✓' if correct else '✗'}  "
                    f"({latency}s) [${total_k_cost:.5f}]  [{len(verdicts)}/{total}]"
                )
                if len(verdicts) >= total:
                    break

    consumer.close()

    # Build records and summary
    records = []
    for post_id, entry in submitted.items():
        row = entry["row"]
        truth_label = row["cleaned_truthfulness"]
        expected = _LABEL_MAP.get(truth_label, "NEI")
        bv = verdicts.get(post_id)
        verdict = bv.verdict if bv else None
        justification = bv.justification if bv else None
        correct = verdict == expected if verdict else False
        image_filenames = image_qrels.get(row["claim_id"], [])
        records.append({
            "post_id": post_id,
            "dataset_claim_id": row["claim_id"],
            "claim_text": row["Claim"],
            "snopes_url": row["Snopes URL"],
            "truth_label": truth_label,
            "system_verdict": verdict,
            "justification": justification,
            "correct": correct,
            "latency_seconds": latencies.get(post_id),
            "costs": bv.costs if bv else {},
            "images_submitted": [
                fn for fn in image_filenames
                if (Path(IMAGES_DIR) / fn).exists()
            ],
        })

    completed = sum(1 for r in records if r["system_verdict"] is not None)
    correct_count = sum(1 for r in records if r["correct"])
    per_label: dict[str, dict] = {}
    for r in records:
        if r["system_verdict"] is not None:
            lbl = r["truth_label"]
            if lbl not in per_label:
                per_label[lbl] = {"total": 0, "correct": 0}
            per_label[lbl]["total"] += 1
            if r["correct"]:
                per_label[lbl]["correct"] += 1

    model_name = os.getenv("MODEL_NAME", "openai/gpt-4o-mini")
    avg_latency = sum(r.get("latency_seconds") or 0.0 for r in records if r.get("system_verdict")) / completed if completed > 0 else 0.0
    avg_cost = sum(sum((r.get("costs") or {}).values()) for r in records if r.get("system_verdict")) / completed if completed > 0 else 0.0
    
    return {
        "mode": "basic",
        "model": model_name,
        "total_submitted": total,
        "completed": completed,
        "correct": correct_count,
        "accuracy": correct_count / completed if completed > 0 else 0.0,
        "avg_latency_seconds": avg_latency,
        "avg_cost": avg_cost,
        "per_label": per_label,
        "records": records,
    }


def run_basic(sample: list[dict], image_qrels: dict[str, list[str]]) -> dict:
    """Submits claims to basic_agent via Kafka and collects verdicts."""
    print(f"Submitting {len(sample)} claim(s) to basic_agent via Kafka...\n")
    submitted = submit_basic_claims(sample, image_qrels)
    print(f"\nSubmitted {len(submitted)}/{len(sample)} claim(s).\n")
    if not submitted:
        return {}
    return poll_basic_verdicts(submitted, image_qrels)


# ─── Output ───────────────────────────────────────────────────────────────────

def write_results(results: dict, label: str = "") -> Path:
    """Writes results to a timestamped JSON file and returns the path."""
    out_dir = Path(__file__).parent / "eval_results"
    out_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    json_path = out_dir / f"eval_{timestamp}{suffix}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    return json_path


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="MOCHEG evaluation runner")
    parser.add_argument(
        "--claim-ids", nargs="+", metavar="ID",
        help="One or more MOCHEG claim IDs (e.g. --claim-ids 9484 8033). "
             "If omitted, a random sample of SAMPLE_SIZE is used.",
    )
    parser.add_argument(
        "--basic", action="store_true",
        help="Basic agent mode: classify claims with gpt-4o-mini using text + inline images. "
             "No tool use, no search, no pipeline.",
    )
    args = parser.parse_args()

    claims = load_unique_claims(Path(CORPUS_PATH))
    print(f"Loaded {len(claims)} unique claims from MOCHEG test set")

    if args.claim_ids:
        requested = set(str(cid) for cid in args.claim_ids)
        sample = [c for c in claims if c["claim_id"] in requested]
        missing = requested - {c["claim_id"] for c in sample}
        if missing:
            print(f"WARNING: claim IDs not found in corpus: {', '.join(sorted(missing))}")
        print(f"Selected {len(sample)} specific claim(s): {', '.join(c['claim_id'] for c in sample)}")
    else:
        rng = random.Random(RANDOM_SEED)
        sample = rng.sample(claims, min(SAMPLE_SIZE, len(claims)))
    
    # test with a basic agent (benchmark/control)
    if args.basic:
        image_qrels = load_image_qrels(Path(IMG_QRELS_PATH))
        print(f"Loaded image qrels for {len(image_qrels)} claims")
        results = run_basic(sample, image_qrels)
        accuracy = results["accuracy"]
        correct = results["correct"]
        completed = results["completed"]
        print(f"\nAccuracy: {correct}/{completed} = {accuracy:.1%}")
        if completed > 0:
            print(f"Average Latency: {results.get('avg_latency_seconds', 0):.1f}s")
            print(f"Average Cost: ${results.get('avg_cost', 0):.5f}")
        for lbl, stats in results["per_label"].items():
            print(f"  {lbl}: {stats['correct']}/{stats['total']}")
        json_path = write_results(results, label="basic")
        print(f"\nResults saved to: {json_path}")
        return

    # EAFC agent framework
    image_qrels = load_image_qrels(Path(IMG_QRELS_PATH))
    print(f"Loaded image qrels for {len(image_qrels)} claims")
    print(f"Submitting {len(sample)} claims to {API_URL}\n")

    submitted_post_ids: set[str] = set()
    for row in sample:
        image_filenames = image_qrels.get(row["claim_id"], [])
        image_urls = upload_claim_images(row["claim_id"], image_filenames)
        payload = {
            "dataset_claim_id": row["claim_id"],
            "claim_text": row["Claim"],
            "snopes_url": row["Snopes URL"],
            "truth_label": row["cleaned_truthfulness"],
            "image_urls": image_urls,
        }
        try:
            data = post_json(API_URL, payload)
            submitted_post_ids.add(data["post_id"])
            print(
                f"  OK  claim_id={row['claim_id']:>6}  "
                f"truth={row['cleaned_truthfulness']:<10}  "
                f"images={len(image_urls)}  "
                f"post_id={data['post_id']}"
            )
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  ERR claim_id={row['claim_id']}  status={e.code}  body={body}")
        except Exception as e:
            print(f"  ERR claim_id={row['claim_id']}  error={e}")

    submitted = len(submitted_post_ids)
    print(f"\nSubmitted {submitted}/{len(sample)} claims successfully.")
    if submitted == 0:
        return

    print(f"Waiting for pipeline to complete (polling every {POLL_INTERVAL}s, timeout {POLL_TIMEOUT}s)...")
    results = poll_until_complete(submitted_post_ids)

    accuracy = results.get("accuracy", 0.0)
    correct = results.get("correct", 0)
    completed = results.get("completed", 0)
    print(f"\nAccuracy: {correct}/{completed} = {accuracy:.1%}")
    if completed > 0:
        print(f"Average Latency: {results.get('avg_latency_seconds', 0):.1f}s")
        print(f"Average Cost: ${results.get('avg_cost', 0):.5f}")
    for lbl, stats in results.get("per_label", {}).items():
        print(f"  {lbl}: {stats['correct']}/{stats['total']}")

    print("Fetching Memgraph artifacts...")
    enrich_with_artifacts(results.get("records", []))

    json_path = write_results(results, label="pipeline")
    print(f"\nResults saved to: {json_path}")

if __name__ == "__main__":
    main()
