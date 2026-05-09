import logging

from shared import graph_client, kafka_client
from shared.models import PostStatus, PostVerdict

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {s.value for s in PostStatus}


def update_post_verdict(post_id: str, verdict: str, justification: str) -> dict:
    """Records the final fact-check verdict and justification for a post.

    Args:
        post_id: The ID of the post to update.
        verdict: The final verdict — one of VERIFIED, REFUTED, NEI, or TBD.
        justification: A concise explanation of the overall reasoning.

    Returns:
        A dict with a 'status' key indicating 'success' or 'failure'.
    """
    if verdict not in _VALID_VERDICTS:
        logger.error(f"Invalid verdict '{verdict}' for post {post_id}")
        return {"status": "failure", "reason": f"verdict must be one of {_VALID_VERDICTS}"}

    try:
        graph_client.update_post_verdict(post_id, verdict, justification)
        logger.info(f"Updated post {post_id} verdict to {verdict}")
    except Exception as e:
        logger.error(f"Failed to update verdict for post {post_id}: {e}")
        return {"status": "failure", "reason": str(e)}

    return {"status": "success"}
