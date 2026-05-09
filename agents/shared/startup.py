"""Startup helpers: wait for Memgraph and Kafka to be reachable before agents begin."""
import logging
import time

logger = logging.getLogger(__name__)

_DEFAULT_RETRIES = 30
_DEFAULT_DELAY = 3.0  # seconds between retries


def wait_for_memgraph(max_retries: int = _DEFAULT_RETRIES, delay: float = _DEFAULT_DELAY) -> None:
    """Blocks until a Bolt connection to Memgraph succeeds or raises RuntimeError."""
    from shared import graph_client

    for attempt in range(1, max_retries + 1):
        try:
            graph_client.get_driver().verify_connectivity()
            logger.info("Memgraph is ready.")
            return
        except Exception as exc:
            logger.warning(f"Memgraph not ready (attempt {attempt}/{max_retries}): {exc}")
            if attempt < max_retries:
                time.sleep(delay)

    raise RuntimeError(f"Memgraph did not become available after {max_retries} attempts.")


def wait_for_kafka(max_retries: int = _DEFAULT_RETRIES, delay: float = _DEFAULT_DELAY) -> None:
    """Blocks until Kafka topics can be ensured or raises RuntimeError."""
    from shared import kafka_client

    for attempt in range(1, max_retries + 1):
        try:
            kafka_client.ensure_topics()
            logger.info("Kafka is ready.")
            return
        except Exception as exc:
            logger.warning(f"Kafka not ready (attempt {attempt}/{max_retries}): {exc}")
            if attempt < max_retries:
                time.sleep(delay)

    raise RuntimeError(f"Kafka did not become available after {max_retries} attempts.")


def wait_for_services() -> None:
    """Waits for both Memgraph and Kafka to be ready. Call once at agent startup."""
    logger.info("Waiting for Memgraph...")
    wait_for_memgraph()
    logger.info("Waiting for Kafka...")
    wait_for_kafka()



