import logging

from fastapi import APIRouter

from shared import graph_client, kafka_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/admin/reset", status_code=204)
async def reset_graph() -> None:
    """Wipes all nodes and relationships from the graph database,
    and purges all Kafka topic messages by deleting and recreating every topic.
    Use during development to clear stale data after schema changes.
    """
    graph_client.delete_all_nodes()
    logger.info("Graph reset via admin endpoint")
    kafka_client.purge_topics()
    logger.info("Kafka topics purged via admin endpoint")
