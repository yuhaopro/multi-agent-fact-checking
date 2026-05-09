import asyncio
import logging
import json
import time

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from shared import graph_client, kafka_client
from shared.models import Evidence, PostCompletion, RetrievalRequest
from shared.cost import calculate_event_cost
import uuid
logger = logging.getLogger(__name__)
model_name = "gemini-3.1-flash-lite-preview"

def parse_search_results(raw: str) -> list[dict]:
    results = []
    if not raw:
        return results
    
    for chunk in raw.split("||"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            results.append(json.loads(chunk))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse search result chunk: {e}\nChunk: {chunk}")
    
    return results

async def _process_query(
    msg: RetrievalRequest, runner: Runner, session_service: InMemorySessionService
) -> None:

    post = graph_client.get_post_node(msg.post_id)
    post_content = post.get("content", "")
    

    session = await session_service.create_session(
        app_name="evidence_retrieval",
        user_id="system",
        state={
            "PostContent": post_content,
            "QueryContent": msg.query_content,
        },
    )
    user_msg = types.Content(
        role="user",
        parts=[types.Part(
            text=f"Retrieve evidences with the provided query related to the provided post content."
        )],
    )
    
    total_cost = 0.0
    
    async for event in runner.run_async(
        user_id="system", session_id=session.id, new_message=user_msg
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                logger.info(
                    f"[evidence_retrieval] tool call → {part.function_call.name}"
                    f"({part.function_call.args})"
                )
            elif hasattr(part, "function_response") and part.function_response:
                logger.info(
                    f"[evidence_retrieval] tool response ← {part.function_response.name}: "
                    f"{str(part.function_response.response)[:500]}"
                )
            elif hasattr(part, "text") and part.text and event.is_final_response():
                logger.info(f"[evidence_retrieval] final response: {part.text[:300]}")
                
        if hasattr(event, "usage_metadata") and event.usage_metadata:
            total_cost += calculate_event_cost(model_name, event.usage_metadata)
    
    updated_session = await session_service.get_session(
        app_name="evidence_retrieval",
        user_id="system",
        session_id=session.id
    )

    search_results_raw = ""
    if not updated_session is None:
        logger.info(f"full session state: {updated_session.state}")
        search_results_raw = updated_session.state.get("search_results", "")
        logger.info(f"raw_search_results: {search_results_raw}")

    await session_service.delete_session(
        app_name="evidence_retrieval", user_id="system", session_id=session.id
    )
    logger.info(f"Finished evidence retrieval for query {msg.query_id}")
    evidences = parse_search_results(search_results_raw)
    logger.info(f"evidences: {evidences}")

    if msg.post_id and total_cost > 0:
        graph_client.add_agent_cost(msg.post_id, "evidence_retrieval", total_cost)

    for evidence in evidences:
        if evidence["published_at"] == None:
            evidence["published_at"] = ""
        try:
            ev = Evidence(url=evidence["url"], title=evidence["title"], content=evidence["content"], published_at=evidence["published_at"], status="COMPLETED")
            graph_client.create_evidence_node(ev)
            graph_client.connect_evidence_to_query(ev.id, msg.query_id)
        except Exception as e:
            logger.warning(f"Failed to create evidence for {evidence}: {e}")
    
    try:
        graph_client.update_query_status(msg.query_id, "COMPLETED")
    except Exception as e:
        logger.warning(f"Failed to update query status: {e}")
    
    try:
        if graph_client.all_post_processing_completed(msg.post_id):
            if graph_client.try_claim_post_for_judging(msg.post_id):
                completion = PostCompletion(post_id=msg.post_id)
                kafka_client.get_producer().send(
                    kafka_client.POST_COMPLETION_TOPIC,
                    value=completion.model_dump_json().encode(),
                )
                kafka_client.get_producer().flush()
                logger.info(f"Safety-net PostCompletion fired for post {msg.post_id}")

    except Exception as e:
        logger.warning(f"post_processing check failed for post {msg.post_id}: {e}")


def start_evidence_retrieval_listener(
    runner: Runner, session_service: InMemorySessionService
) -> None:
    consumer = kafka_client.new_consumer(
        kafka_client.EVIDENCE_RETRIEVAL_TOPIC, kafka_client.EVIDENCE_RETRIEVAL_GROUP
    )
    logger.info(f"[*] Kafka listener started for topic: {kafka_client.EVIDENCE_RETRIEVAL_TOPIC}")
    loop = asyncio.new_event_loop()
    try:
        for msg in consumer:
            if msg.value is None:
                logger.warning(f"Skipping null/tombstone message at offset {msg.offset}")
                consumer.commit()
                continue
            try:
                query = RetrievalRequest.model_validate_json(msg.value)
            except Exception as e:
                logger.error(f"Failed to unmarshal RetrievalRequest: {e}")
                consumer.commit()
                continue
            logger.info(
                f"Processing query at offset {msg.offset}: "
                f"query={query.query_id} query_content={query.query_content!r}"
            )
            try:
                loop.run_until_complete(_process_query(query, runner, session_service))
                consumer.commit()
                time.sleep(2)  # stay under free-tier RPM limit
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    logger.warning(
                        f"Rate limited on query {query.query_id} — sleeping 60s before retry"
                    )
                    time.sleep(60)
                else:
                    logger.error(
                        f"Agent run error for query {query.query_id}: {e} — offset not committed, will reprocess on restart"
                    )
    finally:
        consumer.close()
        loop.close()
