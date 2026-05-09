import asyncio
import logging
import re
import os
import time

from shared.cost import calculate_event_cost

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from shared import graph_client, kafka_client
from shared.models import PostQueryRequest, RetrievalRequest
from query_generation_agent.tools import create_query_node

logger = logging.getLogger(__name__)

_QUERY_LINE_RE = re.compile(r"\d+\.\s*(.+)", re.IGNORECASE)


def _parse_queries(proposed_queries: str) -> list[str]:
    """Parses proposer output into a list of query strings.

    Handles both:
    - Legacy: plain numbered list ("1. query text")
    - DnD format: a "Queries:" section followed by a numbered list
    """
    lines = proposed_queries.strip().splitlines()

    # Try to find a "Queries:" section header
    queries_start = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("queries:"):
            queries_start = i + 1
            break

    if queries_start is not None:
        # Only parse lines after the "Queries:" header
        search_lines = lines[queries_start:]
    else:
        search_lines = lines

    results = []
    for line in search_lines:
        m = _QUERY_LINE_RE.match(line.strip())
        if m:
            results.append(m.group(1).strip())
    return results


async def _execute_query(
    post_id: str,
    post_url: str,
    post_content: str,
    query_text: str,
    executor_runner: Runner,
    executor_session_service: InMemorySessionService,
) -> float:
    session = await executor_session_service.create_session(
        app_name="query_executor",
        user_id="system",
        state={
            "PostID": post_id,
            "PostURL": post_url,
            "PostContent": post_content,
            "QueryText": query_text,
        },
    )
    user_msg = types.Content(
        role="user",
        parts=[types.Part(text=f"Execute query for post {post_id}: {query_text}")],
    )
    cost = 0.0
    model_name = os.getenv("SEARCH_MODEL_NAME", "gemini-2.5-flash")
    if model_name == "gemini-2.5-flash":
        model_name = "gemini/gemini-2.5-flash"
    
    async for event in executor_runner.run_async(
        user_id="system", session_id=session.id, new_message=user_msg
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                logger.info(
                    f"[query_executor] tool call → {part.function_call.name}"
                    f"({part.function_call.args})"
                )
        if hasattr(event, "usage_metadata") and event.usage_metadata:
            cost += calculate_event_cost(model_name, event.usage_metadata)
    await executor_session_service.delete_session(
        app_name="query_executor", user_id="system", session_id=session.id
    )
    logger.info(f"Finished executor for query_text={query_text!r} post={post_id}")
    return cost


async def _process_post(
    req: PostQueryRequest,
    runner: Runner,
    session_service: InMemorySessionService,
) -> None:

    try:
        graph_client.set_post_start_time(req.post_id, time.time())
    except Exception as e:
        logger.warning(f"Failed to set agent_start_time for post {req.post_id}: {e}")

    session = await session_service.create_session(
        app_name="query_generation",
        user_id="system",
        state={
            "PostID": req.post_id,
            "PostContent": req.content,
            "PostURL": req.url,
            "proposed_queries": "",
            "critic_feedback": "",
        },
    )

    user_msg = types.Content(
        role="user",
        parts=[types.Part(text=f"Generate queries for post {req.post_id}.")],
    )
    
    total_cost = 0.0
    model_name = os.getenv("MODEL_NAME", "openai/gpt-4o-mini")
    
    async for event in runner.run_async(
        user_id="system", session_id=session.id, new_message=user_msg
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                logger.info(
                    f"[query_generation] tool call → {part.function_call.name}"
                    f"({part.function_call.args})"
                )
            elif hasattr(part, "text") and part.text and event.is_final_response():
                logger.info(f"[query_generation] final response: {part.text[:300]}")
        
        if hasattr(event, "usage_metadata") and event.usage_metadata:
            total_cost += calculate_event_cost(model_name, event.usage_metadata)

    final_session = await session_service.get_session(
        app_name="query_generation", user_id="system", session_id=session.id
    )
    critic_feedback = final_session.state.get("critic_feedback", "") if final_session else ""
    proposed_queries = final_session.state.get("proposed_queries", "") if final_session else ""

    await session_service.delete_session(
        app_name="query_generation", user_id="system", session_id=session.id
    )

    # default if critic don't approve then use default post content.
    producer = kafka_client.get_producer()
    if critic_feedback.strip().upper().startswith("APPROVED"):
        queries = _parse_queries(proposed_queries)
        logger.info(f"Critic approved {len(queries)} queries for post {req.post_id}")

        for query_text in queries:
            query_node = create_query_node(post_id=req.post_id, query_text=query_text)
            query_id = query_node.get("query_id", "")

            msg = RetrievalRequest(
                post_id = req.post_id,
                query_id=query_id,
                query_content=query_text,
            )
            producer.send(
                kafka_client.EVIDENCE_RETRIEVAL_TOPIC,
                value=msg.model_dump_json().encode(),
            )
    else:
        logger.warning(
            f"Queries not approved for post {req.post_id} "
            f"(feedback: {critic_feedback[:100]!r}) — default to post content"
        )
        
        query_node = create_query_node(post_id=req.post_id, query_text=req.content)
        query_id = query_node.get("query_id", "")

        msg = RetrievalRequest(
            post_id = req.post_id,
            query_id=query_id,
            query_content=req.content,
        )
        producer = kafka_client.get_producer()
        producer.send(
            kafka_client.EVIDENCE_RETRIEVAL_TOPIC,
            value=msg.model_dump_json().encode(),
        )

    producer.flush()
        
    graph_client.add_agent_cost(req.post_id, "query_generation", total_cost)

    logger.info(f"Finished query generation for post {req.post_id}")

def start_post_query_listener(
    runner: Runner,
    session_service: InMemorySessionService,
) -> None:
    consumer = kafka_client.new_consumer(
        kafka_client.POST_QUERY_TOPIC, kafka_client.QUERY_GENERATION_GROUP
    )
    logger.info(f"[*] Kafka listener started for topic: {kafka_client.POST_QUERY_TOPIC}")
    loop = asyncio.new_event_loop()
    try:
        for msg in consumer:
            if msg.value is None:
                logger.warning(f"Skipping null/tombstone message at offset {msg.offset}")
                consumer.commit()
                continue
            try:
                req = PostQueryRequest.model_validate_json(msg.value)
            except Exception as e:
                logger.error(f"Failed to unmarshal PostQueryRequest: {e}")
                consumer.commit()
                continue
            logger.info(
                f"Received PostQueryRequest at offset {msg.offset}: post_id={req.post_id}"
            )
            # Guard: skip stale messages whose Post node was deleted from Memgraph
            try:
                graph_client.get_post_node(req.post_id)
            except ValueError:
                logger.warning(
                    f"Post {req.post_id} not found in Memgraph — stale message, skipping."
                )
                consumer.commit()
                continue
            try:
                loop.run_until_complete(
                    _process_post(req, runner, session_service)
                )
                consumer.commit()
            except Exception as e:
                logger.error(
                    f"Agent run error for post {req.post_id}: {e} — offset not committed, will reprocess on restart"
                )
    finally:
        consumer.close()
        loop.close()
