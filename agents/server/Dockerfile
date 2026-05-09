# Build context must be the agents/ workspace root so uv can resolve the
# workspace and install the shared package.
#
#   docker build -f server/Dockerfile -t fact-check-server .
#
# In docker-compose use:
#   build:
#     context: ../agents
#     dockerfile: server/Dockerfile

# ── Stage 1: install workspace dependencies ───────────────────────────────────
FROM python:3.12-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy only the workspace metadata first — changes to source won't bust this layer.
COPY pyproject.toml uv.lock ./
COPY shared/ ./shared/

RUN uv sync --frozen

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Bring the virtualenv from the build stage.
COPY --from=deps /app/.venv /app/.venv

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# shared source is required because it is installed as an editable package.
COPY shared/ ./shared/
COPY server/ ./server/

EXPOSE 8081

# Run uvicorn from the server/ directory so that local imports (routers,
# services) resolve correctly — the same pattern used by the agent processes.
CMD ["sh", "-c", "cd /app/server && uvicorn main:app --host 0.0.0.0 --port 8081"]
