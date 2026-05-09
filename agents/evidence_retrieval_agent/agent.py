import logging
import os
import signal
import threading

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.tools.google_search_tool import google_search


from listener import start_evidence_retrieval_listener, model_name
from shared import graph_client, kafka_client
from shared.startup import wait_for_services
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


_INSTRUCTION = """You are an Evidence Retrieval Search Agent powered with google search tool.

QueryContent: {QueryContent}
PostContent: {PostContent}

Based on the full context in PostContent and the query in QueryContent, 
I want you to use google_search tool to retrieve relevant evidences to the post based off the query.

Output the search results using the following json format delimited with '||':
{
    "url": "<exact URL from search tool result>",
    "title": "<exact title from search tool result>",
    "content": "<exact content snippet from search tool result>",
    "published_at": "<published date if available, else null>"
}

Examples:
{
    "url": "https://www.politifact.com/factchecks/2020/sep/04/joe-biden/making-point-overlooked-black-history-biden-misses/",
    "title": "A Black man invented the light bulb, not a white guy named Edison.",
    "content": "Biden is referring to Lewis Latimer, an inventor from the same time as Thomas Edison.
        Edison is widely credited with inventing the lightbulb, but he built on the work of many others in developing a practical version of an incandescent filament in a vacuum chamber.
        Latimer built further on that work by inventing a superior filament, which he patented a year after Edison's bulb.
        So both played a role, but Latimer's role was lesser and later.",
    "published_at": "04-08-2022"
}||{
    "url": "https://www.politifact.com/factchecks/2021/nov/02/kelda-helen-roys/yes-five-abortion-restrictions-took-away-services-/",
    "title": "Says gubernatorial candidate Rebecca Kleefisch “worked with Scott Walker to sign five abortion restrictions into law that took away services and threatened doctors with prison time for providing safe and legal abortions.",
    "content": "During his time in office, former Gov. Scott Walker signed several abortion restrictions that former Lt. Gov. Rebecca Kleefisch, now a gubernatorial candidate, supported. These included a ban on abortions after 20 weeks, which carried a punishment of up to 3.5 years in prison for providers who violated it — limits on medication abortions, prohibiting abortion coverage through the health care exchange, requiring providers to have hospital admitting privileges, and barring providers from receiving state family planning grants. While Walker was the driving force behind these restrictions, Kleefisch has long positioned herself as a pro-life candidate, and pro-life groups have credited her with a role in some of them.",
    "published_at": "02-11-2022"
}
"""

def main() -> None:
    load_dotenv()
    wait_for_services()

    evidence_retrieval_agent = LlmAgent(
        name="evidence_retrieval",
        model=model_name,
        description="Retrieve evidences using google search given a query and it's background context",
        instruction=_INSTRUCTION,
        output_key="search_results",
        tools=[google_search],
    )

    session_service = InMemorySessionService()
    runner = Runner(
        agent=evidence_retrieval_agent,
        app_name="evidence_retrieval",
        session_service=session_service,
    )

    t = threading.Thread(
        target=start_evidence_retrieval_listener,
        args=(runner, session_service),
        daemon=True,
    )
    t.start()

    shutdown = threading.Event()

    def _handle_signal(*_):
        logger.info("Shutting down evidence_retrieval agent...")
        shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    shutdown.wait()

    graph_client.close_driver()
    kafka_client.close_producer()


if __name__ == "__main__":
    main()
