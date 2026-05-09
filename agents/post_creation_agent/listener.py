import asyncio
import logging
from datetime import datetime

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from shared import kafka_client, graph_client
from shared.models import URLSubmission
from shared.cost import calculate_event_cost
import state
import os

logger = logging.getLogger(__name__)


async def _process_url(
    submission: URLSubmission,
    runner: Runner,
    session_service: InMemorySessionService,
) -> None:
    session = await session_service.create_session(
        app_name="post_creation",
        user_id="system",
        state={"url": submission.url},
    )
    user_msg = types.Content(
        role="user",
        parts=[types.Part(text=f"URL: {submission.url}")],
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
                    f"[post_creation] tool call → {part.function_call.name}"
                    f"({part.function_call.args})"
                )
            elif hasattr(part, "text") and part.text and event.is_final_response():
                logger.info(f"[post_creation] final response: {part.text[:300]}")
                
        if hasattr(event, "usage_metadata") and event.usage_metadata:
            total_cost += calculate_event_cost(model_name, event.usage_metadata)
            
    await session_service.delete_session(
        app_name="post_creation", user_id="system", session_id=session.id
    )
    logger.info(f"Finished processing URL submission {submission.id}: {submission.url}")
    
    post_id = state.created_posts.pop(submission.url, None)
    if post_id:
        graph_client.set_post_start_time(post_id, datetime.fromisoformat(submission.submitted_at.replace("Z", "+00:00")).timestamp())
        graph_client.add_agent_cost(post_id, "post_creation", total_cost)


def start_url_submission_listener(
    runner: Runner, session_service: InMemorySessionService
) -> None:
    consumer = kafka_client.new_consumer(
        kafka_client.URL_SUBMISSION_TOPIC, kafka_client.URL_SUBMISSION_GROUP
    )
    logger.info(f"[*] Kafka Listener started for topic: {kafka_client.URL_SUBMISSION_TOPIC}")
    loop = asyncio.new_event_loop()
    try:
        for msg in consumer:
            if msg.value is None:
                logger.warning(f"Skipping null/tombstone message at offset {msg.offset}")
                consumer.commit()
                continue
            try:
                submission = URLSubmission.model_validate_json(msg.value)
            except Exception as e:
                logger.error(f"Failed to unmarshal URL submission: {e}")
                consumer.commit()
                continue
            logger.info(
                f"Processing URL submission at offset {msg.offset}: {submission.url}"
            )
            try:
                loop.run_until_complete(_process_url(submission, runner, session_service))
                consumer.commit()
            except Exception as e:
                logger.error(f"Agent run error for submission {submission.id}: {e} — offset not committed, will reprocess on restart")
    finally:
        consumer.close()
        loop.close()
