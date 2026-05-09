# Fact-Check Pipeline

An end-to-end automated fact-checking system. Submit any article URL or social media post and a five-stage multi-agent pipeline retrieves evidence and returns a **VERIFIED**, **REFUTED**, or **NEI** verdict.

---

## Architecture overview

```
frontend (Next.js)
    └── /api/backend  →  FastAPI backend (agents/server)
                              ├── Kafka  (message bus between agents)
                              ├── Memgraph  (graph DB — Posts, Queries, Evidence, Media)
                              └── MinIO  (object storage)

Pipeline agents (Google ADK + LiteLLM):
  post_creation_agent  →  query_generation_agent  →  evidence_retrieval_agent
                                                   →  media_verification_service
                                                   →  post_judge_agent
```

---

## Repo structure

| Path | Description |
|------|-------------|
| `frontend/` | Next.js frontend — dashboard, eval, and logs pages |
| `agents/` | Python pipeline agents, FastAPI backend, and eval tooling |
| `agents/server/` | FastAPI server exposing the REST API consumed by the frontend |
| `agents/eval_runner.py` | CLI batch eval runner against the MOCHEG dataset |
| `agents/analyze.ipynb` | Jupyter notebook for plotting eval results |
| `DESIGN.md` | Zapier-inspired design system reference |

---

## Prerequisites

- Node.js 18+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose

---

## Setup

### 1. Install Python dependencies

```bash
cd agents
uv sync
```

### 2. Configure environment variables

Copy `.env.example` to `.env` inside `agents/` and fill in the values:

```
OPENAI_API_KEY=...
TAVILY_API_KEY=...
MODEL_NAME=openai/gpt-4o-mini
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

### 3. Install frontend dependencies

```bash
cd frontend
npm install
```

---

## Running

### Start the full stack (recommended)

```bash
cd agents
docker compose up -d
```

This starts all pipeline agents, the FastAPI backend, Kafka, Memgraph, and MinIO.

| Service | Description |
|---------|-------------|
| `backend` | FastAPI server at `http://localhost:8000` |
| `post_creation_agent` | Scrapes submitted URLs and creates Post nodes |
| `query_generation_agent` | Decomposes claims into atomic search queries |
| `evidence_retrieval_agent` | Runs Tavily searches and stores evidence |
| `post_judge_agent` | Reviews all evidence and returns a verdict via a judge–critic loop |
| `media_verification_service` | Downloads images and checks for AI-generated content |

Scale agents for higher throughput:

```bash
docker compose up -d --scale query_generation_agent=5 --scale evidence_retrieval_agent=5 --scale post_judge_agent=5
```

### Start the frontend

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000`.

---

## Frontend pages

### Dashboard (`/`)

- Submit any article URL or social media post (Twitter/X, Reddit, Facebook, Instagram, TikTok, YouTube, LinkedIn)
- Real-time five-stage pipeline tracker shows progress as the claim moves through each agent
- Final verdict card shows **VERIFIED / REFUTED / NEI** with justification and evidence sources
- Admin panel to reset the Memgraph graph and Kafka topics

### Evaluation (`/eval`)

Three tabs:

| Tab | Description |
|-----|-------------|
| **Free Claim** | Inject claim text directly — skips URL scraping, enters at query generation. Optional ground-truth label enables accuracy tracking. |
| **MOCHEG Batch** | Randomly sample claims from the MOCHEG test set and run them through the pipeline with real-time accuracy and latency stats. |
| **Results** | Aggregate accuracy, per-label breakdown, average latency, and total cost for all evaluated claims. |

### Agent Logs (`/logs`)

Chat-style conversation view showing what each agent received and produced for any post. Switch between Post Creation, Query Generation, Evidence Retrieval, Media Verification, and Post Judge tabs. Polls live until the verdict is final.

---

## REST API

The FastAPI backend (`agents/server`) exposes the following endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/posts` | Submit a URL for fact-checking |
| `GET` | `/posts` | List all posts |
| `GET` | `/posts/{post_id}` | Get post details (queries, evidence, media) |
| `POST` | `/eval/submit` | Submit a raw claim text for eval |
| `GET` | `/eval/mocheg/claims` | Preview a MOCHEG sample (`?sample=N&seed=S`) |
| `POST` | `/eval/batch` | Run a MOCHEG batch evaluation |
| `GET` | `/eval/results` | Get all evaluation results |
| `POST` | `/admin/reset` | Wipe all graph data and purge Kafka topics |

---

## CLI evaluation

See [`agents/README.md`](agents/README.md) for full instructions on:

- Running the `eval_runner.py` CLI against the MOCHEG dataset
- Analysing results with the `analyze.ipynb` notebook
- Useful Memgraph Cypher queries for debugging
