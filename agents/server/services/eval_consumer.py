import logging
import threading
from datetime import datetime, timezone

from shared import graph_client, kafka_client
from shared.models import PostVerdict
from services import eval_store

logger = logging.getLogger(__name__)


def _parse_iso(ts: str) -> datetime | None:
    """Parses an ISO timestamp string into a timezone-aware datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def start_eval_consumer() -> threading.Thread:
    t = threading.Thread(target=_consume, daemon=True, name="eval-consumer")
    t.start()
    return t


def _consume() -> None:
    consumer = kafka_client.new_consumer(
        kafka_client.POST_VERDICT_TOPIC, kafka_client.POST_VERDICT_GROUP
    )
    logger.info(f"[*] Eval consumer started for topic: {kafka_client.POST_VERDICT_TOPIC}")
    try:
        for msg in consumer:
            if msg.value is None:
                continue
            try:
                verdict = PostVerdict.model_validate_json(msg.value)
            except Exception as e:
                logger.error(f"Failed to parse PostVerdict message: {e}")
                continue

            latency_seconds = verdict.latency_seconds
            costs = verdict.costs
            eval_store.record_verdict(verdict.post_id, verdict.verdict, latency_seconds, costs)
            logger.info(
                f"Eval: recorded verdict for post {verdict.post_id}: {verdict.verdict} "
                f"(latency={latency_seconds:.1f}s) Costs: {costs}" if latency_seconds is not None
                else f"Eval: recorded verdict for post {verdict.post_id}: {verdict.verdict}"
            )
    finally:
        consumer.close()
