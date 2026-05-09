import logging

from shared import graph_client, kafka_client
from shared.models import PostCompletion

logger = logging.getLogger(__name__)


def create_evidence(
    evidence_id: str,
    title: str,
    content: str,
    published_at: str = "",
) -> dict:
    """Marks the pre-created evidence record as COMPLETED with the retrieved content,
    then triggers post judgment if all evidence for the post is now ready.

    Args:
        evidence_id: The id of the pre-created PENDING evidence node to update.
        title: The title or headline of the article.
        content: The full extracted article text as-is.
        published_at: The article's publication date (e.g. "2021-09-18"). Leave empty if unknown.

    Returns:
        A dict with a 'status' key indicating 'success' or 'failure'.
    """
    try:
        graph_client.update_evidence_to_completed(evidence_id, title, content, published_at)
        logger.info(f"Marked evidence {evidence_id} as COMPLETED")
    except Exception as e:
        logger.error(f"Failed to update evidence {evidence_id} to COMPLETED: {e}")
        return {"status": "failure", "reason": str(e)}

    # Find the post this query belongs to and check if all evidence is done.
    # Look up the query that owns this evidence node, then get the post_id.
    # Use an atomic claim to ensure only ONE replica publishes PostCompletion,
    # even if multiple replicas finish their last evidence item simultaneously.
    try:
        # Traverse: Evidence → Query → Post via the graph
        query_node = graph_client.get_query_node_for_evidence(evidence_id)
        post_id = query_node.get("post_id", "") if query_node else ""
        if post_id and graph_client.all_post_processing_completed(post_id):
            if graph_client.try_claim_post_for_judging(post_id):
                msg = PostCompletion(post_id=post_id)
                producer = kafka_client.get_producer()
                producer.send(
                    kafka_client.POST_COMPLETION_TOPIC,
                    value=msg.model_dump_json().encode(),
                )
                producer.flush()
                logger.info(f"All evidence complete — published PostCompletion for post {post_id}")
            else:
                logger.info(f"PostCompletion for post {post_id} already claimed by another replica — skipping")
    except Exception as e:
        logger.error(f"Failed to check/publish PostCompletion for evidence {evidence_id}: {e}")
        return {"status": "failure", "reason": str(e)}

    return {"status": "success"}
