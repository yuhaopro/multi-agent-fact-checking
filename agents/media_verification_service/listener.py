import logging
from datetime import datetime, timezone

from shared import graph_client, kafka_client
from shared.models import Media, PostCompletion
from tools import download_and_upload, verify_ai_generation

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _process_media(media: Media) -> None:
    now = _now()
    media_params = {
        "id": media.id,
        "url": media.url,
        "type": media.type,
        "status": "PENDING",
        "created_at": now,
        "updated_at": now,
    }
    try:
        graph_client.create_and_connect_media(media_params, media.post_id)
        logger.info(f"Created media node {media.id} linked to post {media.post_id!r}")
    except Exception as e:
        logger.error(f"Failed to create media node {media.id}: {e}")
        return

    # Step 1: Download the image and upload to MinIO
    result = download_and_upload(media.id, media.url)
    storage_url = result.get("storage_url", "")

    # Step 2: Run AI-generation detection using the MinIO URL
    if storage_url:
        verify_ai_generation(media.id, storage_url)
    else:
        logger.warning(f"Skipping AI detection for media {media.id} — upload failed")

    # Step 3: Mark media SUCCESS if uploaded to MinIO, FAILED otherwise
    final_status = "SUCCESS" if storage_url else "FAILED"
    try:
        graph_client.update_media_status(media.id, final_status)
        logger.info(f"Media {media.id} marked as {final_status}")
    except Exception as e:
        logger.error(f"Failed to update status for media {media.id}: {e}")

    # Step 4: If all media for the post is processed, trigger the post judge
    try:
        if graph_client.all_media_processed_for_post(media.post_id):
            payload = PostCompletion(post_id=media.post_id).model_dump_json().encode()
            kafka_client.get_producer().send(kafka_client.POST_COMPLETION_TOPIC, payload)
            kafka_client.get_producer().flush()
            logger.info(f"All media processed for post {media.post_id} — published PostCompletion")
    except Exception as e:
        logger.error(f"Failed to check/publish PostCompletion for post {media.post_id}: {e}")

    logger.info(f"Finished processing media {media.id}")


def start_media_creation_listener() -> None:
    consumer = kafka_client.new_consumer(
        kafka_client.MEDIA_CREATION_TOPIC, kafka_client.MEDIA_CREATION_GROUP
    )
    logger.info(f"[*] Kafka listener started for topic: {kafka_client.MEDIA_CREATION_TOPIC}")
    try:
        for msg in consumer:
            if msg.value is None:
                logger.warning(f"Skipping null/tombstone message at offset {msg.offset}")
                consumer.commit()
                continue
            try:
                media = Media.model_validate_json(msg.value)
            except Exception as e:
                logger.error(f"Failed to unmarshal media message: {e}")
                consumer.commit()
                continue
            logger.info(f"Processing Media at offset {msg.offset}: media_id={media.id} url={media.url}")
            try:
                _process_media(media)
                consumer.commit()
            except Exception as e:
                logger.error(
                    f"Processing error for media {media.id}: {e} — offset not committed, will reprocess on restart"
                )
    finally:
        consumer.close()
