import logging
import os
import signal
import threading

from dotenv import load_dotenv
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.google_search_tool import google_search

from shared import kafka_client
from shared.startup import wait_for_services
from listener import start_basic_claim_listener
from tools import record_basic_verdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_SEARCH_INSTRUCTION = """\
You are a search agent helping fact-check a claim.

Post ID : {PostID}
Claim   : {ClaimText}

Use google_search to find relevant, recent sources about the claim.
Run 2-3 targeted searches using concise queries derived from the key assertion.

Return a concise summary of what you found: the main facts, any contradictions,
and the most relevant source titles/snippets. Do not give a verdict yet.
"""

_FACT_CHECK_INSTRUCTION = """\
You are a fact-checking assistant.

Post ID       : {PostID}
Claim         : {ClaimText}

Search results gathered by the search agent:
{search_results}

Using the search results above (and any images provided), classify the claim as
exactly one of:
  VERIFIED — the claim is true based on the evidence
  REFUTED  — the claim is false based on the evidence
  NEI      — not enough information to determine truthfulness

Guidelines:
- Visual evidence in images should carry significant weight.
- Use REFUTED only when the claim is clearly and explicitly contradicted.
- Use VERIFIED only when the evidence confirms the core/central assertion.
  Confirmation of the main claim is sufficient even if minor details are imprecise.
  *** Be diligent: If the search results contain any information that confirms 
  the claim, do not default to NEI. ***
- Use NEI only when evidence is truly absent, irrelevant, or shows the claim 
  is genuinely contested/ambiguous. 
  *** GUARD: Do NOT return NEI if there is relevant supporting or refuting 
  text in the search results. ***

Call record_basic_verdict with:
  - post_id      : the Post ID above
  - verdict      : VERIFIED, REFUTED, or NEI
  - justification: 1-3 sentences citing the key evidence found (or explaining
                   why evidence was insufficient for NEI)
"""


def main() -> None:
    load_dotenv()
    wait_for_services()

    model_name = "openai/gpt-5-mini"
    # model_name = "gemini-2.5-flash"
    # model_name = "anthropic/claude-3-haiku-20240307"
    search_model = "gemini-2.5-flash"

    search_agent = LlmAgent(
        name="search_agent",
        model=search_model,
        description="Searches Google for evidence about the claim and returns a summary.",
        instruction=_SEARCH_INSTRUCTION,
        tools=[google_search],
        output_key="search_results",
    )

    fact_checker = LlmAgent(
        name="fact_checker",
        model=LiteLlm(model=model_name),
        # model=model_name,
        description="Classifies a claim as VERIFIED, REFUTED, or NEI based on search results and images.",
        instruction=_FACT_CHECK_INSTRUCTION,
        tools=[record_basic_verdict],
    )

    pipeline = SequentialAgent(
        name="basic_fact_checker_pipeline",
        sub_agents=[search_agent, fact_checker],
    )


    session_service = InMemorySessionService()
    runner = Runner(
        agent=pipeline,
        app_name="basic_agent",
        session_service=session_service,
    )

    t = threading.Thread(
        target=start_basic_claim_listener,
        args=(runner, session_service),
        daemon=True,
    )
    t.start()

    shutdown = threading.Event()

    def _handle_signal(*_):
        logger.info("Shutting down basic_agent...")
        shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    shutdown.wait()

    kafka_client.close_producer()


if __name__ == "__main__":
    main()
