import logging
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from shared import graph_client, storage_client

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def download_and_upload(media_id: str, image_url: str) -> dict:
    """Downloads the image from image_url, uploads it to MinIO, and updates
    the Media node with the resulting storage_url.

    Returns a dict with 'storage_url' on success, or 'status': 'failure'.
    """
    suffix = Path(image_url).suffix or ".jpg"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        urllib.request.urlretrieve(image_url, tmp_path)
        logger.info(f"Downloaded {image_url!r} → {tmp_path}")
    except Exception as e:
        logger.error(f"Failed to download image {image_url!r}: {e}")
        return {"status": "failure", "reason": str(e)}

    try:
        object_key = f"media/{media_id}/image{suffix}"
        storage_url = storage_client.upload_file(tmp_path, object_key)
    except Exception as e:
        logger.error(f"Failed to upload image for media {media_id}: {e}")
        return {"status": "failure", "reason": str(e)}
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    try:
        graph_client.update_media_node(media_id, storage_url=storage_url, updated_at=_now())
    except Exception as e:
        logger.error(f"Failed to persist storage_url for media {media_id}: {e}")

    return {"storage_url": storage_url}


def verify_ai_generation(media_id: str, storage_url: str) -> dict:
    """Checks whether the image at storage_url was AI-generated or is a deepfake.
    Updates the Media node with the result.

    Returns a dict with 'is_ai_generated' and 'ai_score'.
    """
    # TODO: integrate a real AI-detection API (e.g. Hive, Sightengine)
    is_ai_generated = False
    ai_score = 0.0
    try:
        graph_client.update_media_node(
            media_id,
            is_ai_generated=is_ai_generated,
            ai_score=ai_score,
            updated_at=_now(),
        )
        logger.info(f"AI detection for media {media_id}: is_ai_generated={is_ai_generated} score={ai_score}")
    except Exception as e:
        logger.error(f"Failed to save AI detection result for media {media_id}: {e}")
        return {"status": "failure", "reason": str(e)}
    return {"is_ai_generated": is_ai_generated, "ai_score": ai_score}
