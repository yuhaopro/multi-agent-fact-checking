import asyncio
import json
import logging
import re
import urllib.request

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, vertex_ai_session_service
from google.genai import types

from shared import graph_client, kafka_client
from shared.models import PostCompletion, PostVerdict
from shared.cost import calculate_event_cost
import os
import time
import json

logger = logging.getLogger(__name__)
def parse_verdict(raw: str) -> dict:
    if not raw or not raw.strip():
        logger.warning("verdict_draft is empty, defaulting to NEI")
        return {"verdict": "NEI", "justification": ""}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            fixed = re.sub(r'"verdict"\s*:\s*([A-Z]+)', r'"verdict": "\1"', clean)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse verdict JSON, defaulting to NEI. Raw: {raw[:200]!r}")
                return {"verdict": "NEI", "justification": raw}

def _image_part(storage_url: str) -> types.Part | None:
    """Fetches an image from MinIO and returns it as an inline Part for the LLM.
    Remaps binary/octet-stream to the correct image MIME type from file magic bytes.
    """
    _MAGIC = [
        (b"\x89PNG",         "image/png"),
        (b"GIF8",            "image/gif"),
        (b"RIFF",            "image/webp"),
        (b"\xff\xd8\xff",    "image/jpeg"),
    ]
    try:
        with urllib.request.urlopen(storage_url, timeout=15) as resp:
            data = resp.read()
            mime_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        # MinIO often returns generic binary/octet-stream; detect real type from magic bytes
        if mime_type in ("binary/octet-stream", "application/octet-stream"):
            for magic, detected in _MAGIC:
                if data[:len(magic)] == magic:
                    mime_type = detected
                    break
            else:
                mime_type = "image/jpeg"  # safe default for unknown binary
        return types.Part(inline_data=types.Blob(mime_type=mime_type, data=data))
    except Exception as e:
        logger.warning(f"Could not fetch image {storage_url!r} for vision: {e}")
        return None


async def _process_post(
    post_completion: PostCompletion,
    runner: Runner,
    session_service: InMemorySessionService,
) -> None:
    post_id = post_completion.post_id

    try:
        post = graph_client.get_post_node(post_id)
        status = post.get("status", "TBD")
    except Exception as e:
        logger.error(f"Could not fetch post {post_id}: {e}")
        raise e

    if status == "TBD":
        logger.info(f"Deferring post {post_id}: query generation not yet complete (status=TBD)")
        return
    if status not in ("JUDGING",):
        # Verdict already set in Memgraph but PostVerdict may not have reached Kafka
        # (e.g. crash between update_post_verdict and producer.send on a prior attempt).
        # Re-publish PostVerdict so the eval runner is unblocked.
        logger.warning(f"Post {post_id} already has verdict (status={status}), re-publishing PostVerdict to unblock eval runner")
        start_time = post.get("agent_start_time", 0.0)
        latency = round(time.time() - start_time, 1) if start_time else 0.0
        msg = PostVerdict(
            post_id=post_id,
            verdict=status,
            justification=post.get("justification", ""),
            latency_seconds=latency,
            costs=post.get("costs", {}),
        )
        try:
            producer = kafka_client.get_producer()
            producer.send(kafka_client.POST_VERDICT_TOPIC, value=msg.model_dump_json().encode())
            producer.flush()
        except Exception as e:
            logger.warning(f"Failed to re-publish PostVerdict for post {post_id}: {e}")
            raise e
        return

    # Guard: wait for all media to finish processing (SUCCESS or FAILED)
    if not graph_client.all_media_processed_for_post(post_id):
        logger.info(f"Skipping post {post_id}: media verification still in progress")
        return

    queries_with_evidence = graph_client.get_all_evidences_for_post(post_id)

    logger.info(f"queries with evidences: {queries_with_evidence}")
    media = graph_client.get_media_for_post(post_id)

    # Fetch each successfully processed image from MinIO as an inline part
    image_parts: list[types.Part] = []
    for item in media:
        storage_url = item.get("storage_url", "")
        if storage_url and item.get("status") == "SUCCESS":
            part = _image_part(storage_url)
            if part:
                image_parts.append(part)
                logger.info(f"Attached image {storage_url!r} to judge prompt for post {post_id}")

    post_node = graph_client.get_post_node(post_id)
    post_content = post_node.get("content", "")


    session = await session_service.create_session(
        app_name="post_judge",
        user_id="system",
        state={
            "PostContent": post_content,
            "QueriesJSON": json.dumps(queries_with_evidence, indent=2, default=str),
            "MediaJSON": json.dumps(media, indent=2, default=str),
            "verdict_draft": "",
            "critic_feedback": "",
        },
    )

    user_msg = types.Content(
        role="user",
        parts=[
            types.Part(text=f"Determine the final verdict for post {post_id}."),
            *image_parts,
        ],
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
                    f"[post_judge] tool call → {part.function_call.name}"
                    f"({part.function_call.args})"
                )
            elif hasattr(part, "text") and part.text and event.is_final_response():
                logger.info(f"[post_judge] final response: {part.text[:300]}")
        
        if hasattr(event, "usage_metadata") and event.usage_metadata:
            total_cost += calculate_event_cost(model_name, event.usage_metadata)
    
    updated_session = await session_service.get_session(
        app_name="post_judge", user_id="system", session_id=session.id
    )
    if updated_session:
        verdict_draft_raw = updated_session.state.get("verdict_draft", "")
        verdict_draft = parse_verdict(verdict_draft_raw)
        logger.info(f"verdict_draft:  {verdict_draft}")
        verdict = verdict_draft.get("verdict", "NEI")
        justification = verdict_draft.get("justification", "")

        try:
            graph_client.update_post_verdict(post_id=post_id, verdict=verdict, justification=justification)
        except Exception as e:
            logger.warning(f"Failed to update post verdict for post {post_id}: {e}")
            raise e
        try:
            graph_client.add_agent_cost(post_id, "post_judge", total_cost)
        except Exception as e:
            logger.warning(f"Failed to add post_judge cost for post {post_id}: {e}")
        updated_post = graph_client.get_post_node(post_id)
        all_costs = updated_post.get("costs", {})
        start_time = post_node.get("agent_start_time", 0.0)
        latency = round(time.time() - start_time, 1) if start_time else 0.0
        msg = PostVerdict(
            post_id=post_id,
            verdict=verdict,
            justification=justification,
            latency_seconds=latency,
            costs=all_costs
        )
        try:
            producer = kafka_client.get_producer()
            producer.send(kafka_client.POST_VERDICT_TOPIC, value=msg.model_dump_json().encode())
            producer.flush()
            logger.info(f"Published PostVerdict for post {post_id} ({latency}s) Costs: {all_costs}")
        except Exception as e:
            logger.warning(f"Failed to publish PostVerdict for post {post_id}: {e}")
            raise e

    await session_service.delete_session(
        app_name="post_judge", user_id="system", session_id=session.id
    )
    logger.info(f"Finished reviewing post {post_id}")




def start_post_completion_listener(
    runner: Runner, session_service: InMemorySessionService
) -> None:
    consumer = kafka_client.new_consumer(
        kafka_client.POST_COMPLETION_TOPIC, kafka_client.POST_COMPLETION_GROUP
    )
    logger.info(f"[*] Kafka Listener started for topic: {kafka_client.POST_COMPLETION_TOPIC}")
    loop = asyncio.new_event_loop()
    try:
        for msg in consumer:
            if msg.value is None:
                logger.warning(f"Skipping null/tombstone message at offset {msg.offset}")
                consumer.commit()
                continue
            try:
                post_completion = PostCompletion.model_validate_json(msg.value)
            except Exception as e:
                logger.error(f"Failed to unmarshal post completion message: {e}")
                consumer.commit()
                continue
            logger.info(
                f"Processing PostCompletion at offset {msg.offset}: "
                f"post_id={post_completion.post_id}"
            )
            try:
                loop.run_until_complete(
                    _process_post(post_completion, runner, session_service)
                )
                consumer.commit()
            except Exception as e:
                logger.error(
                    f"Agent run error for post {post_completion.post_id}: {e} — offset not committed, will reprocess on restart"
                )
                
    finally:
        consumer.close()
        loop.close()
