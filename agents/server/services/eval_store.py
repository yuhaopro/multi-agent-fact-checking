import threading
from dataclasses import dataclass
from typing import Optional

# Maps MOCHEG truth labels to the system's internal verdict strings
_LABEL_MAP: dict[str, str] = {
    "supported": "VERIFIED",
    "refuted": "REFUTED",
    "NEI": "NEI",
}


@dataclass
class EvalRecord:
    post_id: str
    dataset_claim_id: str
    truth_label: str  # MOCHEG label: supported | refuted | NEI
    claim_text: str = ""
    snopes_url: str = ""
    system_verdict: Optional[str] = None  # system label: VERIFIED | REFUTED | NEI
    correct: Optional[bool] = None
    latency_seconds: Optional[float] = None
    costs: Optional[dict[str, float]] = None


_store: dict[str, EvalRecord] = {}
_lock = threading.Lock()


def register(
    post_id: str,
    dataset_claim_id: str,
    truth_label: str,
    claim_text: str = "",
    snopes_url: str = "",
) -> None:
    """Registers a submitted eval claim so its verdict can be validated later."""
    with _lock:
        _store[post_id] = EvalRecord(
            post_id=post_id,
            dataset_claim_id=dataset_claim_id,
            truth_label=truth_label,
            claim_text=claim_text,
            snopes_url=snopes_url,
        )


def record_verdict(post_id: str, verdict: str, latency_seconds: Optional[float] = None, costs: Optional[dict[str, float]] = None) -> None:
    """Called when the pipeline produces a verdict; compares against truth label."""
    with _lock:
        record = _store.get(post_id)
        if not record:
            return
        record.system_verdict = verdict
        record.latency_seconds = latency_seconds
        record.costs = costs if costs is not None else {}
        expected = _LABEL_MAP.get(record.truth_label)
        record.correct = verdict == expected


def get_results() -> dict:
    """Returns current accuracy metrics across all submitted eval claims."""
    with _lock:
        records = list(_store.values())

    total = len(records)
    completed = sum(1 for r in records if r.system_verdict is not None)
    correct = sum(1 for r in records if r.correct)

    per_label: dict[str, dict] = {}
    for r in records:
        if r.system_verdict is not None:
            lbl = r.truth_label
            if lbl not in per_label:
                per_label[lbl] = {"total": 0, "correct": 0}
            per_label[lbl]["total"] += 1
            if r.correct:
                per_label[lbl]["correct"] += 1

    return {
        "total_submitted": total,
        "completed": completed,
        "correct": correct,
        "accuracy": correct / completed if completed > 0 else 0.0,
        "per_label": per_label,
        "records": [
            {
                "post_id": r.post_id,
                "dataset_claim_id": r.dataset_claim_id,
                "truth_label": r.truth_label,
                "claim_text": r.claim_text,
                "snopes_url": r.snopes_url,
                "system_verdict": r.system_verdict,
                "correct": r.correct,
                "latency_seconds": r.latency_seconds,
                "costs": r.costs,
            }
            for r in records
        ],
    }
