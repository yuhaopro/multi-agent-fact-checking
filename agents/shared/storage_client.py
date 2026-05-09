"""MinIO / S3-compatible object storage client shared across all agents."""
import logging
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

BUCKET = os.getenv("MINIO_BUCKET", "media")

_s3: boto3.client = None  # type: ignore[assignment]


def get_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
            aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            region_name="us-east-1",  # required by boto3, ignored by MinIO
        )
    return _s3


def ensure_bucket() -> None:
    """Creates the media bucket if it does not already exist and sets it to public-read."""
    client = get_client()
    try:
        client.head_bucket(Bucket=BUCKET)
    except ClientError:
        client.create_bucket(Bucket=BUCKET)
        # Allow public read so agents and the judge can fetch images by URL
        client.put_bucket_policy(
            Bucket=BUCKET,
            Policy=f'{{"Version":"2012-10-17","Statement":[{{"Effect":"Allow",'
                   f'"Principal":"*","Action":"s3:GetObject","Resource":"arn:aws:s3:::{BUCKET}/*"}}]}}',
        )
        logger.info(f"Created MinIO bucket '{BUCKET}' with public-read policy")


def upload_file(local_path: str, object_key: str) -> str:
    """Uploads a local file to MinIO and returns its public URL.

    Args:
        local_path: Absolute path to the local file.
        object_key: Key (path) within the bucket, e.g. "media/{media_id}/image.jpg".

    Returns:
        The public URL of the uploaded object.
    """
    ensure_bucket()
    get_client().upload_file(local_path, BUCKET, object_key)
    public_url = f"{os.getenv('MINIO_PUBLIC_URL')}/{BUCKET}/{object_key}"
    logger.info(f"Uploaded {local_path!r} → {public_url}")
    return public_url
