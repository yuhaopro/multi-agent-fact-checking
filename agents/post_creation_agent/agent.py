import logging
import os
import signal
import threading

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from mcp import StdioServerParameters
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams


from listener import start_url_submission_listener
from tools import create_post, publish_media
from shared import graph_client, kafka_client
from shared.startup import wait_for_services

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


_INSTRUCTION = """You are a Post Creation Agent.
You receive a URL to a social media post or article that needs to be fact-checked.
The URL is: {url}

STEP 1 — Extract the page content
    Use tavily-extract with url: {url} to retrieve the page content.

    STOP IMMEDIATELY without calling any further tools if:
    - The extraction fails or returns an error
    - The result is empty or contains no meaningful text
    - The content is clearly a login wall, paywall, or access-denied page
    Simply end the task with a short explanation of why it was skipped.

    Otherwise extract from the result:
    - title: the main headline or page title (plain text, no URLs)
    - content: the article or post body text only — strip navigation, ads,
      footers, and boilerplate. Keep only human-readable written content.
    - image_urls: any image URLs present in the result that the author
      intentionally included as part of their message (photos, charts, media).
      EXCLUDE site chrome, logos, avatars, tracking pixels, and ad images.
      If unsure whether an image belongs to the authored content, leave it out.

STEP 2 — Create the post record
    Call create_post with:
    - url: {url}
    - title: the extracted title (at most one sentence)
    - content: the extracted text content (no image URLs embedded in it)

    create_post returns a post_id — save it for the next step.

STEP 3 — Register images for verification
    For each image URL found in Step 1:
    - Call publish_media with post_id (from Step 2) and image_url.
    - Call once per unique image URL.
    - Do NOT describe or interpret image content.
    - If no images were found, skip this step entirely.

After all tool calls are complete, output nothing. Do not summarise, confirm, or explain your actions.
"""


def main() -> None:
    load_dotenv()
    wait_for_services()

    model_name = os.getenv("MODEL_NAME", "openai/gpt-4o")
    model = LiteLlm(model=model_name)

    tavily_mcp = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "tavily-mcp@latest"],
                env={"TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", "")},
            ),
            timeout=30.0,
        )
    )

    post_creation_agent = LlmAgent(
        name="post_creation",
        model=model,
        description="Extracts post content and images via Tavily, creates the post record, and routes media for verification.",
        instruction=_INSTRUCTION,
        tools=[tavily_mcp, create_post, publish_media],
    )



    session_service = InMemorySessionService()
    runner = Runner(
        agent=post_creation_agent,
        app_name="post_creation",
        session_service=session_service,
    )

    t = threading.Thread(
        target=start_url_submission_listener,
        args=(runner, session_service),
        daemon=True,
    )
    t.start()

    shutdown = threading.Event()

    def _handle_signal(*_):
        logger.info("Shutting down post_creation agent...")
        shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    shutdown.wait()

    graph_client.close_driver()
    kafka_client.close_producer()


if __name__ == "__main__":
    main()
