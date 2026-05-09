import logging
import os
import signal
import threading

from dotenv import load_dotenv
from google.adk.agents import LlmAgent, LoopAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai.types import Content, Part
from mcp import StdioServerParameters

from listener import start_post_query_listener
from shared import graph_client, kafka_client
from shared.startup import wait_for_services



logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_PROPOSER_INSTRUCTION = """You are a Query Proposer Agent.

Post ID  : {PostID}
Post URL : {PostURL}
Content  :
  "{PostContent}"

Previous critic feedback (if any):
  {critic_feedback}

────────────────────────────────────────────────────────────────────────────────
STEP 1 — DnD ANALYSIS (Decompose and Decontextualize Jointly)

First, break the post into its verifiable atomic subclaims. Then, decontextualize
each subclaim so that it is self-contained and can be searched without the
surrounding context.

Format this section as:

  DnD Subclaims:
  - <original subclaim 1> → <decontextualized subclaim 1>
  - <original subclaim 2> → <decontextualized subclaim 2>
  ...

Example (claim: "He first gained recognition in the mid-1990s for his starring
role in 'Schindler's List', directed by Steven Spielberg."):

  DnD Subclaims:
  - He gained recognition in the mid-1990s.              → Liam Neeson gained recognition in the mid-1990s.
  - His recognition was for a starring role.             → Liam Neeson's recognition was for a starring role.
  - His starring role was in 'Schindler's List'.         → Liam Neeson's starring role was in the film 'Schindler's List'.
  - 'Schindler's List' was directed by Steven Spielberg. → 'Schindler's List' was directed by Steven Spielberg.

────────────────────────────────────────────────────────────────────────────────
STEP 2 — QUERY GENERATION

Based on the decontextualized subclaims above, propose the MINIMUM number of
search queries needed to verify the distinct verifiable claims, but ensure EACH query is STRICTLY ATOMIC:
- Each query MUST contain exactly ONE question or search intent.
- Do NOT combine multiple questions into a single query (e.g., NEVER write "Did X happen? What were the penalties?").
- If a claim requires answering multiple distinct questions, split them into separate queries (e.g., Query 1: "Did X happen?", Query 2: "What were the penalties for X?").
- Use the decontextualized form in the queries — include key named entities,
  organisations, dates, and specific figures.

If critic feedback is present, address every issue raised before producing new proposals.

Format your final queries as:

  Queries:
  1. <search query string>
  2. <search query string>   (only if truly needed)

No extra commentary outside the two sections above.
"""

_CRITIC_INSTRUCTION = """You are a Query Critic Agent.

Post ID  : {PostID}
Post URL : {PostURL}

Proposed queries:
{proposed_queries}

The proposer may have included a "DnD Subclaims" section before the queries.
IGNORE the DnD section entirely — only validate lines that appear under "Queries:"
or are numbered query strings ("1. ...", "2. ...", etc.).

VALIDATE the proposed queries against these rules:

  IMPORTANT — check the list size first:
    • If there is exactly 1 query and the post is clearly about a single verifiable fact,
      this is the CORRECT output. Do NOT apply REDUNDANT or DUPLICATE.

  Rules that apply when there are 2 or more queries:
  1. DUPLICATE  — Nearly identical wording to another proposed query.
  2. REDUNDANT  — Targets the same verifiable aspect as another query, even if
                  worded differently.
  3. UNFOCUSED  — Too vague to return useful fact-checking results.
  4. OFF_TOPIC  — Does not relate to a specific verifiable claim in the post.

  • If ANY proposed query fails any rule:
      Output: NEEDS_REFINEMENT: <brief explanation of each issue>

  • If ALL queries pass:
      Output exactly: APPROVED
"""


def _exit_loop_if_approved(callback_context: CallbackContext) -> Content | None:
    """Before the proposer runs, check if the critic already approved.
    If so, escalate to exit the LoopAgent early."""
    feedback = callback_context.state.get("critic_feedback", "")
    if isinstance(feedback, str) and feedback.strip().upper().startswith("APPROVED"):
        callback_context.actions.escalate = True
        return Content(
            role="model",
            parts=[Part(text="Queries approved by critic. Exiting refinement loop.")],
        )
    return None


def main() -> None:
    load_dotenv()

    wait_for_services()

    model = LiteLlm(model="openai/gpt-5-mini")

    # tavily_mcp = McpToolset(
    #     connection_params=StdioConnectionParams(
    #         server_params=StdioServerParameters(
    #             command="npx",
    #             args=["-y", "tavily-mcp@latest"],
    #             env=dict(
    #                 TAVILY_API_KEY=os.getenv("TAVILY_API_KEY", ""),
    #                 DEFAULT_PARAMETERS=os.getenv("TAVILY_DEFAULT_PARAMETERS", "")
    #             ),
    #         ),
    #         timeout=30.0,
    #     )
    # )

    proposer_agent = LlmAgent(
        name="query_proposer",
        model=model,
        description="Proposes independent search queries to verify the factual claims in a post.",
        instruction=_PROPOSER_INSTRUCTION,
        output_key="proposed_queries",
        before_agent_callback=_exit_loop_if_approved,
    )

    critic_agent = LlmAgent(
        name="query_critic",
        model=model,
        description="Reviews proposed queries for duplicates and redundancy.",
        instruction=_CRITIC_INSTRUCTION,
        output_key="critic_feedback",
    )

    refinement_loop = LoopAgent(
        name="query_refinement_loop",
        sub_agents=[proposer_agent, critic_agent],
        max_iterations=3,
    )


    session_service = InMemorySessionService()
    runner = Runner(
        agent=refinement_loop,
        app_name="query_generation",
        session_service=session_service,
    )

    t = threading.Thread(
        target=start_post_query_listener,
        args=(runner, session_service),
        daemon=True,
    )
    t.start()

    shutdown = threading.Event()

    def _handle_signal(*_):
        logger.info("Shutting down query_generation agent...")
        shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    shutdown.wait()

    graph_client.close_driver()
    kafka_client.close_producer()


if __name__ == "__main__":
    main()
