# Fact-Checking Agent Pipeline

A multi-agent fact-checking system built with Google ADK and LiteLLM. Claims are submitted to a pipeline of agents — post creation, query generation, evidence retrieval, and verdict judging — coordinated via Kafka and stored in Memgraph.

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose

---

## Setup

**1. Install dependencies**
```bash
uv sync
```

**2. Configure environment variables**

Copy `.env.example` to `.env` and fill in the required values:
```
OPENAI_API_KEY=...
TAVILY_API_KEY=...
MODEL_NAME=openai/gpt-4o-mini
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

**3. Start infrastructure**
```bash
docker compose up -d memgraph kafka minio
```

---

## Running the Pipeline Agents

Start all agents and the backend server with Docker Compose:
```bash
docker compose up -d
```

This starts the following services:
| Service | Description |
|---|---|
| `backend` | FastAPI server exposing the submission and eval API |
| `post_creation_agent` | Receives claim submissions and creates Post nodes in Memgraph |
| `query_generation_agent` | Decomposes claims into atomic search queries |
| `evidence_retrieval_agent` | Runs Tavily searches and stores retrieved evidence |
| `post_judge_agent` | Reviews all evidence and produces a VERIFIED / REFUTED / NEI verdict via a judge–critic loop |
| `media_verification_service` | Downloads and AI-deepfake-checks any images attached to a post |

To scale agents for higher throughput (e.g. 5 replicas):
```bash
docker compose up -d --scale query_generation_agent=5 --scale evidence_retrieval_agent=5 --scale post_judge_agent=5
```

To tail logs for a specific agent:
```bash
docker compose logs -f post_judge_agent
```

To stop everything:
```bash
docker compose down
```

---

## MOCHEG Dataset

The batch eval feature requires the MOCHEG test corpus to be present on disk. Download the dataset and place the test split at:

```
agents/mocheg/test/Corpus2.csv
```

The CSV must contain the columns `claim_id`, `Claim`, `cleaned_truthfulness` (values: `supported`, `refuted`, `NEI`), and `Snopes URL`. Without this file the `POST /api/v1/eval/batch` and `GET /api/v1/eval/mocheg/claims` endpoints return 404.

The MOCHEG dataset is available at: https://github.com/VT-NLP/Mocheg

---

## Running the Eval Runner

The eval runner reads claims from the MOCHEG test set, submits them through the pipeline, waits for all verdicts, and writes a JSON report to `eval_results/`.

**Full pipeline — random 100-claim sample:**
```bash
uv run python eval_runner.py
```

**Full pipeline — specific claim IDs:**
```bash
uv run python eval_runner.py --claim-ids 9484 8033 5562
```

**Basic agent (single LLM call, no query/evidence pipeline):**
```bash
uv run python eval_runner.py --basic
```

**Basic agent — specific claim IDs:**
```bash
uv run python eval_runner.py --basic --claim-ids 9484 8033
```

Results are saved to `eval_results/eval_<timestamp>_pipeline.json` (or `_basic.json`). Each file contains overall accuracy, per-label accuracy, average latency, average cost, and a full record for every evaluated claim.

---

## Analysing Results

Open the analysis notebook:
```bash
uv run jupyter notebook analyze.ipynb
```

The notebook contains five charts:

| Cell | Chart | Description |
|---|---|---|
| 1 | Accuracy by Version | Line chart of overall accuracy across pipeline prompt versions v1–v4 |
| 2 | Avg Cost by Version | Line chart of average cost per claim (in m$) across versions v1–v4 |
| 3 | Accuracy by Token Length | Grouped bar chart comparing baseline vs refined pipeline accuracy, binned by claim word count |
| 4 | Avg Cost by Token Length | Same comparison for cost |
| 5 | Avg Latency by Token Length | Same comparison for latency |

Charts 3–5 show both the metric value and sample size `(n=X)` above each bar.

All charts are automatically saved as high-resolution EPS files to `eval_results/plots/` when the notebook is run, suitable for direct inclusion in LaTeX documents:
```latex
\includegraphics[width=\textwidth]{fig/accuracy_by_version.eps}
```

To run the text-based confusion matrix and retrieval stats against the latest eval file:
```bash
uv run python analyze_eval.py
# or pass a specific file:
uv run python analyze_eval.py eval_results/eval_20260315_180044_pipeline.json
```

---

## Useful Memgraph Queries

```cypher
-- Inspect a specific post and all connected nodes
MATCH (p:Post {id: '<post_id>'})-[r*1..4]->(n)
RETURN p, r, n;

-- Check queries and evidence for a post
MATCH (p:Post {id: '<post_id>'})-[:HAS_QUERY]->(q:Query)-[:HAS_EVIDENCE]->(e:Evidence)
RETURN p.status, q.query_text, e.title, e.url;

-- Delete all nodes (reset for a fresh eval run)
MATCH (n) DETACH DELETE n;
```
