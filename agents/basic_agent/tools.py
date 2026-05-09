import logging
import time

from shared import kafka_client
from shared.models import BasicVerdict
import state

logger = logging.getLogger(__name__)

_VALID_VERDICTS = {"VERIFIED", "REFUTED", "NEI"}


def record_basic_verdict(post_id: str, verdict: str, justification: str) -> dict:
    """Records the final fact-check verdict for the claim.

    Call this once you have determined the verdict. The verdict must be
    exactly one of: VERIFIED, REFUTED, NEI.

    Args:
        post_id: The ID of the claim being evaluated (from session state PostID).
        verdict: VERIFIED, REFUTED, or NEI.
        justification: A concise 1-3 sentence explanation of the verdict.

    Returns:
        A dict with a 'status' key: 'success' or 'failure'.
    """
    verdict = verdict.strip().upper()
    if verdict not in _VALID_VERDICTS:
        logger.error(f"Invalid verdict '{verdict}' for post {post_id}")
        return {"status": "failure", "reason": f"verdict must be one of {_VALID_VERDICTS}"}

    try:
        # Save to state so listener can calculate and attach full cost and latency
        state.basic_verdicts[post_id] = {
            "verdict": verdict,
            "justification": justification
        }
        logger.info(f"Recorded BasicVerdict in state for post {post_id}: {verdict}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to record BasicVerdict for post {post_id}: {e}")
        return {"status": "failure", "reason": str(e)}
