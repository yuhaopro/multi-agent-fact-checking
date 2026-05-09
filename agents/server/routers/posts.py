import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared import graph_client, kafka_client
from shared.models import URLSubmission

logger = logging.getLogger(__name__)

router = APIRouter()


class SubmitURLRequest(BaseModel):
    url: str


class SubmitURLResponse(BaseModel):
    submission_id: str
    url: str
    message: str


@router.get("/posts")
async def list_posts() -> list[dict]:
    """Returns up to 100 recent posts sorted newest-first."""
    return graph_client.list_posts()


@router.get("/posts/{post_id}")
async def get_post(post_id: str) -> dict:
    """Returns full post detail: post node + queries + evidence + media."""
    try:
        post = graph_client.get_post_node(post_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Post not found")

    queries = graph_client.get_queries_for_post(post_id)
    evidence_by_query = graph_client.get_all_evidences_for_post(post_id)
    media = graph_client.get_media_for_post(post_id)

    return {
        "post": post,
        "queries": queries,
        "evidence_by_query": evidence_by_query,
        "media": media,
    }


@router.post("/posts", response_model=SubmitURLResponse, status_code=202)
async def submit_url(req: SubmitURLRequest) -> SubmitURLResponse:
    """Accepts a URL and queues it for fact-checking. The post will be parsed,
    decomposed into claims, and verified asynchronously by the agent pipeline."""
    submission = URLSubmission(url=req.url)

    try:
        future = kafka_client.get_producer().send(
            kafka_client.URL_SUBMISSION_TOPIC,
            value=submission.model_dump_json().encode(),
        )
        future.get(timeout=10)
    except Exception as exc:
        logger.error(f"Failed to publish URL submission {submission.id}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to queue URL for processing")

    logger.info(f"Queued URL submission {submission.id}: {req.url}")
    return SubmitURLResponse(
        submission_id=submission.id,
        url=req.url,
        message="URL accepted and queued for fact-checking",
    )
