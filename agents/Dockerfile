# ── Stage 1: install workspace dependencies ───────────────────────────────────
FROM python:3.12-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy workspace definition and lockfile first (cache-friendly).
COPY pyproject.toml uv.lock ./
# shared/ must be present for `uv sync` to build the editable install.
COPY shared/ ./shared/

# Sync the full workspace into a virtualenv at /app/.venv
RUN uv sync --frozen

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.12-slim

# Install Node.js (LTS) — required for npx tavily-mcp@latest used by agents.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Virtualenv from deps stage.
COPY --from=deps /app/.venv /app/.venv

# Put the venv on PATH so `python` resolves to the venv interpreter.
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy the shared library source (needed for the editable install path).
COPY shared/ ./shared/

# Copy every agent so that inter-agent imports are never an issue.
# Each agent directory is self-contained (listener.py, tools.py, agent.py).
COPY post_creation_agent/ ./post_creation_agent/
COPY query_generation_agent/ ./query_generation_agent/
COPY evidence_retrieval_agent/ ./evidence_retrieval_agent/
COPY post_judge_agent/ ./post_judge_agent/
COPY media_verification_service/ ./media_verification_service/
COPY basic_agent/ ./basic_agent/

# AGENT_NAME must be set at runtime (via docker-compose `environment:` or -e).
# It controls which agent directory is entered and whose agent.py is executed.
# Example values: post_creation_agent | query_generation_agent | evidence_retrieval_agent | post_judge_agent | media_verification_service | basic_agent
ENV AGENT_NAME=post_judge_agent

# cd into the agent directory so that local imports (listener, tools) resolve
# against the correct package, then launch the agent entry-point.
CMD ["sh", "-c", "cd /app/${AGENT_NAME} && python agent.py"]
