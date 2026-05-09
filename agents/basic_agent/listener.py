import asyncio
import base64
import logging
import time
import os
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from shared import kafka_client
from shared.models import BasicClaimRequest, BasicVerdict
from shared.cost import calculate_event_cost
import state

logger = logging.getLogger(__name__)


def _image_part(image_path: str) -> types.Part | None:
    """Loads a local image file and returns it as an inline Part for the LLM."""
    path = Path(image_path)
    if not path.exists():
        logger.warning(f"Image not found on disk, skipping: {image_path}")
        return None
    suffix = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    mime_type = mime_map.get(suffix, "image/jpeg")
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        return types.Part(
            inline_data=types.Blob(
                mime_type=mime_type,
                data=base64.b64decode(data),
            )
        )
    except Exception as e:
        logger.warning(f"Could not load image {image_path!r}: {e}")
        return None


async def _process_claim(
    req: BasicClaimRequest,
    runner: Runner,
    session_service: InMemorySessionService,
) -> None:
    # Build inline image parts from local paths
    image_parts: list[types.Part] = []
    for img_path in req.image_paths:
        part = _image_part(img_path)
        if part:
            image_parts.append(part)
            logger.info(f"Attached image {img_path!r} for post {req.post_id}")

    state.processing_start_times[req.post_id] = time.time()

    model_name = os.getenv("MODEL_NAME", "openai/gpt-4o-mini")
    search_model = os.getenv("SEARCH_MODEL_NAME", "gemini-2.5-flash")
    total_cost = 0.0

    session = await session_service.create_session(
        app_name="basic_agent",
        user_id="system",
        state={
            "PostID": req.post_id,
            "ClaimText": req.claim_text,
        },
    )

    user_msg = types.Content(
        role="user",
        parts=[
            types.Part(text=f"Fact-check the following claim and record your verdict.\n\nClaim: {req.claim_text}"),
            *image_parts,
        ],
    )

    async for event in runner.run_async(
        user_id="system", session_id=session.id, new_message=user_msg
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                logger.info(
                    f"[basic_agent] tool call → {part.function_call.name}"
                    f"({part.function_call.args})"
                )
            elif hasattr(part, "text") and part.text and event.is_final_response():
                logger.info(f"[basic_agent] final response: {part.text[:300]}")
                
        if hasattr(event, "usage_metadata") and event.usage_metadata:
            agent_name = getattr(event, "agent_name", "fact_checker")
            m_name = search_model if agent_name == "search_agent" else model_name
            if m_name == "gemini-2.5-flash":
                m_name = "gemini/gemini-2.5-flash"
            total_cost += calculate_event_cost(m_name, event.usage_metadata)

    await session_service.delete_session(
        app_name="basic_agent", user_id="system", session_id=session.id
    )
    
    start = state.processing_start_times.pop(req.post_id, None)
    latency = round(time.time() - start, 1) if start else 0.0
    
    verdict_info = state.basic_verdicts.pop(req.post_id, None)
    if not verdict_info:
        logger.warning(f"No basic verdict recorded for post {req.post_id}. Forcing NEI fallback.")
        verdict_info = {
            "verdict": "NEI",
            "justification": "System Error: The basic agent failed to provide a structured verdict (no tool call)."
        }

    msg = BasicVerdict(
        post_id=req.post_id,
        verdict=verdict_info["verdict"],
        justification=verdict_info["justification"],
        latency_seconds=latency,
        costs={"basic_agent": total_cost}
    )
    producer = kafka_client.get_producer()
    producer.send(kafka_client.BASIC_VERDICT_TOPIC, value=msg.model_dump_json().encode())
    producer.flush()
    logger.info(f"Published BasicVerdict for post {req.post_id}: {verdict_info['verdict']} ({latency}s) Cost: ${total_cost:.5f}")
        
    logger.info(f"Finished basic fact-check for post {req.post_id}")


def start_basic_claim_listener(
    runner: Runner,
    session_service: InMemorySessionService,
) -> None:
    consumer = kafka_client.new_consumer(
        kafka_client.BASIC_CLAIM_TOPIC, kafka_client.BASIC_CLAIM_GROUP
    )
    logger.info(f"[*] Kafka listener started for topic: {kafka_client.BASIC_CLAIM_TOPIC}")
    loop = asyncio.new_event_loop()
    try:
        for msg in consumer:
            if msg.value is None:
                logger.warning(f"Skipping null/tombstone message at offset {msg.offset}")
                consumer.commit()
                continue
            try:
                req = BasicClaimRequest.model_validate_json(msg.value)
            except Exception as e:
                logger.error(f"Failed to unmarshal BasicClaimRequest: {e}")
                consumer.commit()
                continue
            logger.info(
                f"Received BasicClaimRequest at offset {msg.offset}: post_id={req.post_id}"
            )
            try:
                loop.run_until_complete(_process_claim(req, runner, session_service))
                consumer.commit()
            except Exception as e:
                logger.error(
                    f"Agent run error for post {req.post_id}: {e} — offset not committed, will reprocess on restart"
                )
    finally:
        consumer.close()
        loop.close()
