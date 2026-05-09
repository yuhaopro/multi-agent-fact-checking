import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from enum import Enum


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uuid() -> str:
    return str(uuid.uuid4())


class PostStatus(Enum):
    TBD = "TBD"
    NEI = "NEI"
    VERIFIED = "VERIFIED"
    REFUTED = "REFUTED"


class Query(BaseModel):
    id: str = Field(default_factory=_uuid)
    post_id: str = ""
    query_text: str = ""
    status: str = "PENDING"
    created_at: str = Field(default_factory=_now_str)
    updated_at: str = Field(default_factory=_now_str)


class PostQueryRequest(BaseModel):
    """Published when a post is ready for query generation."""
    post_id: str
    url: str
    content: str


class Post(BaseModel):
    id: str = Field(default_factory=_uuid)
    url: str = ""
    title: str = ""
    content: str = ""
    status: str = "TBD"
    justification: str = ""
    agent_start_time: float = 0.0
    costs: dict[str, float] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_str)
    updated_at: str = Field(default_factory=_now_str)


class Evidence(BaseModel):
    id: str = Field(default_factory=_uuid)
    title: str = ""
    url: str = ""
    content: str = ""
    published_at: str = ""
    status: str = "PENDING"
    created_at: str = Field(default_factory=_now_str)
    updated_at: str = Field(default_factory=_now_str)


class Media(BaseModel):
    id: str = Field(default_factory=_uuid)
    post_id: str = ""
    url: str = ""
    transcript: str = ""
    type: str = "IMAGE"
    is_ai_generated: bool = False
    ai_detection_result: str = ""
    status: str = "PENDING"
    created_at: str = Field(default_factory=_now_str)
    updated_at: str = Field(default_factory=_now_str)


class PostCompletion(BaseModel):
    post_id: str


class URLSubmission(BaseModel):
    id: str = Field(default_factory=_uuid)
    url: str
    submitted_at: str = Field(default_factory=_now_str)


class RetrievalRequest(BaseModel):
    """Sent from query_generation_agent to evidence_retrieval_agent.
    Carries one article link to retrieve and the pre-created PENDING evidence node id."""
    query_id: str
    query_content: str = ""
    post_id: str


class PostVerdict(BaseModel):
    """Published to POST_VERDICT_TOPIC when the post judge finalises a verdict."""
    post_id: str
    verdict: str
    justification: str
    latency_seconds: float = 0.0
    costs: dict[str, float] = Field(default_factory=dict)


class BasicClaimRequest(BaseModel):
    """Published by eval_runner to request a basic (no-search) fact-check."""
    post_id: str
    claim_text: str
    dataset_claim_id: str = ""
    truth_label: str = ""
    snopes_url: str = ""
    image_paths: list[str] = []  # absolute paths to local MOCHEG images


class BasicVerdict(BaseModel):
    """Published by basic_agent when the fact-check is complete."""
    post_id: str
    verdict: str
    justification: str
    latency_seconds: float = 0.0
    costs: dict[str, float] = Field(default_factory=dict)


