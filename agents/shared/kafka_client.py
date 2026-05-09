import logging
import os

from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

logger = logging.getLogger(__name__)

# ─── Topic names ─────────────────────────────────────────────────────────────
EVIDENCE_RETRIEVAL_TOPIC = "evidence_retrieval"
POST_CREATION_TOPIC = "post_creation"
POST_COMPLETION_TOPIC = "post_completion"
POST_QUERY_TOPIC = "post_query"
POST_VERDICT_TOPIC = "post_verdict"
MEDIA_CREATION_TOPIC = "media_creation"
URL_SUBMISSION_TOPIC = "url_submission"
BASIC_CLAIM_TOPIC = "basic_claim"
BASIC_VERDICT_TOPIC = "basic_verdict"

# ─── Consumer group IDs ───────────────────────────────────────────────────────
POST_CREATION_GROUP = "post-creation-group"
POST_CREATION_MEDIA_CREATION_GROUP = "post-creation-media-creation-group"
QUERY_GENERATION_GROUP = "query-generation-group"
EVIDENCE_RETRIEVAL_GROUP = "evidence-retrieval-group"
MEDIA_CREATION_GROUP = "media-creation-group"
URL_SUBMISSION_GROUP = "url-submission-group"
POST_COMPLETION_GROUP = "post-completion-group"
POST_VERDICT_GROUP = "post-verdict-group"
BASIC_CLAIM_GROUP = "basic-claim-group"

_ALL_TOPICS = [
    URL_SUBMISSION_TOPIC,
    POST_CREATION_TOPIC,
    POST_COMPLETION_TOPIC,
    POST_QUERY_TOPIC,
    EVIDENCE_RETRIEVAL_TOPIC,
    MEDIA_CREATION_TOPIC,
    POST_VERDICT_TOPIC,
    BASIC_CLAIM_TOPIC,
    BASIC_VERDICT_TOPIC,
]

_producer: KafkaProducer | None = None


def get_brokers() -> list[str]:
    return os.getenv("KAFKA_BROKERS", "localhost:9092").split(",")


def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(bootstrap_servers=get_brokers())
    return _producer


def close_producer() -> None:
    global _producer
    if _producer is not None:
        _producer.close()
        _producer = None


def ensure_topics(replication_factor: int = 1) -> None:
    """Creates all pipeline topics if they do not already exist.
    Partition count is read from KAFKA_NUM_PARTITIONS env var (default 1).
    Set KAFKA_NUM_PARTITIONS >= replica count so each replica can consume in parallel.
    Call this once at agent or server startup before producing or consuming.

    Topics are created individually so that a pre-existing topic does not prevent
    newly-added topics from being created (the batch API raises TopicAlreadyExistsError
    for the whole batch if any single topic already exists).
    """
    num_partitions = int(os.getenv("KAFKA_NUM_PARTITIONS", "1"))
    admin = KafkaAdminClient(bootstrap_servers=get_brokers())
    try:
        for topic in _ALL_TOPICS:
            try:
                admin.create_topics(
                    new_topics=[NewTopic(name=topic, num_partitions=num_partitions, replication_factor=replication_factor)],
                    validate_only=False,
                )
                logger.info(f"Created Kafka topic: {topic}")
            except TopicAlreadyExistsError:
                pass  # already exists — nothing to do
            except Exception as e:
                logger.warning(f"Could not create Kafka topic {topic!r}: {e}")
    finally:
        admin.close()
    logger.info(f"Ensured Kafka topics: {_ALL_TOPICS}")


def purge_topics() -> None:
    """Deletes and recreates all pipeline topics, effectively clearing every message.
    Call this only from admin/reset flows — running agents will lose their pending work."""
    admin = KafkaAdminClient(bootstrap_servers=get_brokers())
    try:
        existing = set(admin.list_topics())
        to_delete = [t for t in _ALL_TOPICS if t in existing]
        if to_delete:
            admin.delete_topics(to_delete)
            logger.info(f"Deleted Kafka topics: {to_delete}")
        # Brief pause so the broker finishes the deletion before we recreate
        import time; time.sleep(2)
        num_partitions = int(os.getenv("KAFKA_NUM_PARTITIONS", "1"))
        for topic in _ALL_TOPICS:
            try:
                admin.create_topics(
                    new_topics=[NewTopic(name=topic, num_partitions=num_partitions, replication_factor=1)],
                    validate_only=False,
                )
            except Exception as te:
                logger.warning(f"Could not recreate topic {topic!r}: {te}")
        logger.info(f"Recreated Kafka topics: {_ALL_TOPICS}")
    except Exception as e:
        logger.error(f"Failed to purge Kafka topics: {e}")
        raise
    finally:
        admin.close()


def new_consumer(topic: str, group_id: str) -> KafkaConsumer:
    """Creates a new Kafka consumer for a given topic and group."""
    return KafkaConsumer(
        topic,
        bootstrap_servers=get_brokers(),
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        max_partition_fetch_bytes=10 * 1024 * 1024,  # 10 MB
        # LLM agent processing can take 60-120 s per message.
        # session_timeout_ms must be > heartbeat_interval_ms; the heartbeat
        # thread runs independently, but keep the window generous.
        session_timeout_ms=60_000,
        heartbeat_interval_ms=10_000,
        # max_poll_interval_ms caps how long between poll() calls before the
        # broker kicks the consumer from the group.  10 minutes covers even the
        # slowest LoopAgent run with multiple LLM + MCP calls.
        max_poll_interval_ms=600_000,
    )
