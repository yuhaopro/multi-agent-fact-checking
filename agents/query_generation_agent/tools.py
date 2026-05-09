import logging
import uuid
from datetime import datetime, timezone

from shared import graph_client, kafka_client
from shared.models import RetrievalRequest

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_query_node(post_id: str, query_text: str) -> dict:
    """Creates a Query node in the graph for one verifiable aspect of the post.
    Call this once per query before searching.

    Args:
        post_id: The ID of the post this query belongs to.
        query_text: The search query string to send to Tavily.

    Returns:
        A dict with 'query_id' on success, or 'status': 'failure'.
    """
    query_id = str(uuid.uuid4())
    now = _now()
    query_params = {
        "id": query_id,
        "post_id": post_id,
        "query_text": query_text,
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
    }
    try:
        graph_client.create_and_connect_query(query_params, post_id)
        logger.info(f"Created Query node {query_id} for post {post_id}: query_text={query_text!r}")
        return {"query_id": query_id}
    except Exception as e:
        logger.error(f"Failed to create Query node for post {post_id}: {e}")
        return {"status": "failure", "reason": str(e)}
