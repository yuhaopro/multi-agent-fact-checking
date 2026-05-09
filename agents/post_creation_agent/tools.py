import logging
import uuid
from datetime import datetime, timezone
from html import unescape

from shared import graph_client, kafka_client
from shared.models import Media, Post, PostQueryRequest
import state

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_post(url: str, title: str, content: str) -> dict:
    """Creates a post record in the database and queues it for query generation.

    Args:
        url: The original URL of the post/article.
        title: The title or headline extracted from the page.
        content: The main text body extracted from the page. Must not contain
                 image URLs — only the textual article content.

    Returns:
        A dict with 'status' and 'post_id' on success, or 'status': 'failure'.
    """
    now = _now()
    post = Post(url=url, title=title, content=content)
    post_dict = post.model_dump()
    post_dict["created_at"] = now
    post_dict["updated_at"] = now

    try:
        graph_client.upsert_post(post_dict)
    except Exception as e:
        logger.error(f"Failed to upsert post in graph: {e}")
        return {"status": "failure"}

    combined_content = f"{title}. {content}" if title else content

    try:
        producer = kafka_client.get_producer()
        producer.send(
            kafka_client.POST_CREATION_TOPIC,
            value=post.model_dump_json().encode(),
        )
        query_request = PostQueryRequest(
            post_id=post.id,
            url=url,
            content=combined_content,
        )
        producer.send(
            kafka_client.POST_QUERY_TOPIC,
            value=query_request.model_dump_json().encode(),
        )
        producer.flush()
        logger.info(
            f"Published post {post.id} to {kafka_client.POST_CREATION_TOPIC} "
            f"and queued for query generation on {kafka_client.POST_QUERY_TOPIC}"
        )
    except Exception as e:
        logger.error(f"Failed to publish post {post.id} to Kafka: {e}")
        return {"status": "failure"}

    state.created_posts[url] = post.id
    return {"status": "success", "post_id": post.id}


def publish_media(post_id: str, image_url: str) -> dict:
    """Records an image URL found on the page and queues it for media verification.
    Do NOT interpret or describe the image — only register the raw URL.

    Args:
        post_id: The id of the post returned by create_post.
        image_url: The image URL exactly as found on the page.

    Returns:
        A dict with a 'status' key indicating 'success' or 'failure'.
    """
    media_id = str(uuid.uuid4())
    clean_url = unescape(image_url)

    try:
        media = Media(id=media_id, post_id=post_id, url=clean_url)
        producer = kafka_client.get_producer()
        producer.send(
            kafka_client.MEDIA_CREATION_TOPIC,
            value=media.model_dump_json().encode(),
        )
        producer.flush()
        logger.info(f"Published media {media_id} to {kafka_client.MEDIA_CREATION_TOPIC}")
    except Exception as e:
        logger.error(f"Failed to publish media {media_id} to Kafka: {e}")
        return {"status": "failure"}

    return {"status": "success"}
