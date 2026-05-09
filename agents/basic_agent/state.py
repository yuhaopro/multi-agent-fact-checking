# In-process store for per-claim processing start times.
# Set by listener.py before runner.run_async(); read by tools.py when recording verdict.
processing_start_times: dict[str, float] = {}
basic_verdicts: dict[str, dict] = {}
