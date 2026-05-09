import os
import logging
from datetime import datetime, timezone
from neo4j import GraphDatabase, Driver

from shared.models import Evidence, Post

logger = logging.getLogger(__name__)

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        uri = os.getenv("GRAPH_URI", "bolt://localhost:7687")
        user = os.getenv("GRAPH_USER", "neo4j")
        password = os.getenv("GRAPH_PASSWORD", "neo4j")
        _driver = GraphDatabase.driver(uri, auth=(user, password))
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _node_to_dict(node) -> dict:
    d = {k: node[k] for k in node.keys()}
    if "costs_json" in d:
        import json
        try:
            d["costs"] = json.loads(d["costs_json"])
        except Exception:
            d["costs"] = {}
    return d


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─── Query Operations ─────────────────────────────────────────────────────────

def create_and_connect_query(query: dict, post_id: str) -> None:
    """Upserts a Query node and links it to a Post via HAS_QUERY."""
    with get_driver().session() as s:
        s.execute_write(_create_and_connect_query_tx, query, post_id)


def _create_and_connect_query_tx(tx, query: dict, post_id: str) -> None:
    result = tx.run("MATCH (p:Post {id: $post_id}) RETURN p", post_id=post_id)
    if not result.single():
        raise ValueError(f"Post with id {post_id!r} not found")
    tx.run(
        """
        MATCH (p:Post {id: $post_id})
        MERGE (q:Query {id: $id})
        SET q.post_id    = $post_id,
            q.query_text = $query_text,
            q.status     = $status,
            q.created_at = $created_at,
            q.updated_at = $updated_at
        MERGE (p)-[:HAS_QUERY]->(q)
        """,
        post_id=post_id,
        **{k: v for k, v in query.items() if k != "post_id"},
    )


def get_query_node(query_id: str) -> dict:
    """Retrieves a Query node by ID."""
    with get_driver().session() as s:
        result = s.run("MATCH (q:Query {id: $id}) RETURN q", id=query_id)
        record = result.single()
        if not record:
            raise ValueError(f"Query with id {query_id!r} not found")
        return _node_to_dict(record["q"])


def get_queries_for_post(post_id: str) -> list[dict]:
    """Returns all Query nodes linked to a Post via HAS_QUERY."""
    with get_driver().session() as s:
        result = s.run(
            "MATCH (p:Post {id: $post_id})-[:HAS_QUERY]->(q:Query) RETURN q",
            post_id=post_id,
        )
        return [_node_to_dict(record["q"]) for record in result]


def get_all_evidences_for_post(post_id: str) -> list[dict]:
    """Returns all queries for a post, each with its associated evidence list.
    Shape: [{query_text, evidence: [{id, title, content, url, published_at, status}]}]
    """
    with get_driver().session() as s:
        return s.execute_read(_get_all_evidences_for_post_tx, post_id)


def _get_all_evidences_for_post_tx(tx, post_id: str) -> list[dict]:
    result = tx.run(
        """
        MATCH (p:Post {id: $post_id})-[:HAS_QUERY]->(q:Query)
        OPTIONAL MATCH (q)-[:HAS_EVIDENCE]->(e:Evidence)
        RETURN q, collect(e) AS evidences
        """,
        post_id=post_id,
    )
    out = []
    for record in result:
        q = _node_to_dict(record["q"])
        evidences = [_node_to_dict(e) for e in record["evidences"] if e is not None]
        out.append({
            "query_text": q.get("query_text", ""),
            "evidence": evidences,
        })
    return out


# ─── Evidence Operations ──────────────────────────────────────────────────────

def create_pending_evidence_for_query(evidence: dict, query_id: str) -> None:
    """Creates a PENDING Evidence node and links it to a Query via HAS_EVIDENCE."""
    with get_driver().session() as s:
        s.execute_write(_create_pending_evidence_for_query_tx, evidence, query_id)


def _create_pending_evidence_for_query_tx(tx, evidence: dict, query_id: str) -> None:
    result = tx.run("MATCH (q:Query {id: $query_id}) RETURN q", query_id=query_id)
    if not result.single():
        raise ValueError(f"Query with id {query_id!r} not found")
    tx.run(
        """
        MERGE (e:Evidence {id: $id})
        SET e.url        = $url,
            e.title      = '',
            e.content    = '',
            e.status     = 'PENDING',
            e.created_at = $created_at,
            e.updated_at = $updated_at
        """,
        **evidence,
    )
    tx.run(
        """
        MATCH (q:Query    {id: $query_id})
        MATCH (e:Evidence {id: $evidence_id})
        MERGE (q)-[:HAS_EVIDENCE]->(e)
        """,
        query_id=query_id,
        evidence_id=evidence["id"],
    )


def get_evidence_node(evidence_id: str) -> dict:
    """Retrieves an Evidence node by ID."""
    with get_driver().session() as s:
        result = s.run("MATCH (e:Evidence {id: $id}) RETURN e", id=evidence_id)
        record = result.single()
        if not record:
            raise ValueError(f"Evidence with id {evidence_id!r} not found")
        return _node_to_dict(record["e"])


def create_evidence_node(evidence: Evidence) -> None:
    """Creates a standalone, already-COMPLETED Evidence node (used for internal knowledge)."""
    with get_driver().session() as s:
        s.execute_write(_create_evidence_node_tx, evidence.model_dump())


def _create_evidence_node_tx(tx, evidence: dict) -> None:
    tx.run(
        """
        MERGE (e:Evidence {id: $id})
        SET e.url          = $url,
            e.title        = $title,
            e.content      = $content,
            e.published_at = $published_at,
            e.status       = $status,
            e.created_at   = $created_at,
            e.updated_at   = $updated_at
        """,
        **evidence,
    )


def connect_evidence_to_query(evidence_id: str, query_id: str) -> None:
    """Links an Evidence node to a Query via HAS_EVIDENCE."""
    with get_driver().session() as s:
        s.execute_write(_connect_evidence_to_query_tx, evidence_id, query_id)


def _connect_evidence_to_query_tx(tx, evidence_id: str, query_id: str) -> None:
    tx.run(
        """
        MATCH (q:Query    {id: $query_id})
        MATCH (e:Evidence {id: $evidence_id})
        MERGE (q)-[:HAS_EVIDENCE]->(e)
        """,
        query_id=query_id,
        evidence_id=evidence_id,
    )


def get_query_node_for_evidence(evidence_id: str) -> dict | None:
    """Returns the Query node that owns the given Evidence node, or None if not found."""
    with get_driver().session() as s:
        result = s.run(
            "MATCH (q:Query)-[:HAS_EVIDENCE]->(e:Evidence {id: $id}) RETURN q",
            id=evidence_id,
        )
        record = result.single()
        return _node_to_dict(record["q"]) if record else None


def update_evidence_to_completed(evidence_id: str, title: str, content: str, published_at: str = "") -> None:
    """Updates a PENDING Evidence node to COMPLETED, filling in title, content, and published_at."""
    with get_driver().session() as s:
        s.execute_write(_update_evidence_to_completed_tx, evidence_id, title, content, published_at)


def _update_evidence_to_completed_tx(tx, evidence_id: str, title: str, content: str, published_at: str) -> None:
    now = _now_str()
    tx.run(
        """
        MATCH (e:Evidence {id: $evidence_id})
        SET e.title        = $title,
            e.content      = $content,
            e.published_at = $published_at,
            e.status       = 'COMPLETED',
            e.updated_at   = $updated_at
        """,
        evidence_id=evidence_id,
        title=title,
        content=content,
        published_at=published_at,
        updated_at=now,
    )


def update_query_status(query_id: str, status: str) -> None:
    """Updates the status field of a Query node."""
    with get_driver().session() as s:
        s.execute_write(_update_query_status_tx, query_id, status)


def _update_query_status_tx(tx, query_id: str, status: str) -> None:
    now = _now_str()
    tx.run(
        "MATCH (q:Query {id: $query_id}) SET q.status = $status, q.updated_at = $updated_at",
        query_id=query_id,
        status=status,
        updated_at=now,
    )


def update_query_snippet(query_id: str, snippet: str) -> None:
    """Updates the snippet field of a Query node."""
    with get_driver().session() as s:
        s.execute_write(_update_query_snippet_tx, query_id, snippet)


def _update_query_snippet_tx(tx, query_id: str, snippet: str) -> None:
    now = _now_str()
    tx.run(
        "MATCH (q:Query {id: $query_id}) SET q.snippet = $snippet, q.updated_at = $updated_at",
        query_id=query_id,
        snippet=snippet,
        updated_at=now,
    )


def all_post_evidences_completed(post_id: str) -> bool:
    """Returns True if no PENDING evidence remains across all queries for the post."""
    with get_driver().session() as s:
        return s.execute_read(_all_post_evidences_completed_tx, post_id)


def _all_post_evidences_completed_tx(tx, post_id: str) -> bool:
    result = tx.run(
        """
        MATCH (p:Post {id: $post_id})-[:HAS_QUERY]->(q:Query)-[:HAS_EVIDENCE]->(e:Evidence)
        WHERE e.status = 'PENDING'
        RETURN count(e) AS pending_count
        """,
        post_id=post_id,
    )
    record = result.single()
    return record is not None and record["pending_count"] == 0


def all_post_processing_completed(post_id: str) -> bool:
    """Returns True when all Query nodes for the post are COMPLETED and no Evidence is PENDING.

    A Query is marked COMPLETED by the query_generation_agent after it finishes searching
    (regardless of whether any articles were found). This prevents premature PostCompletion
    when some queries have no evidence nodes yet.
    """
    with get_driver().session() as s:
        return s.execute_read(_all_post_processing_completed_tx, post_id)


def _all_post_processing_completed_tx(tx, post_id: str) -> bool:
    # Check that every Query for this post is COMPLETED
    pending_queries = tx.run(
        """
        MATCH (p:Post {id: $post_id})-[:HAS_QUERY]->(q:Query)
        WHERE q.status <> 'COMPLETED'
        RETURN count(q) AS pending_count
        """,
        post_id=post_id,
    ).single()
    if pending_queries is None or pending_queries["pending_count"] > 0:
        return False

    # Check that no Evidence node is still PENDING
    pending_evidence = tx.run(
        """
        MATCH (p:Post {id: $post_id})-[:HAS_QUERY]->(q:Query)-[:HAS_EVIDENCE]->(e:Evidence)
        WHERE e.status = 'PENDING'
        RETURN count(e) AS pending_count
        """,
        post_id=post_id,
    ).single()
    if pending_evidence is None or pending_evidence["pending_count"] > 0:
        return False

    return True


# ─── Media Operations ─────────────────────────────────────────────────────────

def update_media_node(media_id: str, **fields) -> None:
    """Updates specific fields on a Media node."""
    with get_driver().session() as s:
        s.execute_write(_update_media_node_tx, media_id, fields)


def _update_media_node_tx(tx, media_id: str, fields: dict) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"m.{k} = ${k}" for k in fields)
    tx.run(  # type: ignore[arg-type]
        f"MATCH (m:Media {{id: $media_id}}) SET {set_clause}",
        media_id=media_id,
        **fields,
    )


def create_and_connect_media(media: dict, post_id: str) -> None:
    """Upserts a Media node and links it to a Post via HAS_MEDIA."""
    with get_driver().session() as s:
        s.execute_write(_create_and_connect_media_tx, media, post_id)


def _create_and_connect_media_tx(tx, media: dict, post_id: str) -> None:
    tx.run(
        """
        MERGE (m:Media {id: $id})
        SET m.url        = $url,
            m.type       = $type,
            m.status     = $status,
            m.created_at = $created_at,
            m.updated_at = $updated_at
        """,
        **media,
    )
    result = tx.run("MATCH (p:Post {id: $post_id}) RETURN p", post_id=post_id)
    if not result.single():
        raise ValueError(f"Post with id {post_id} not found")
    tx.run(
        """
        MATCH (m:Media {id: $media_id})
        MATCH (p:Post  {id: $post_id})
        MERGE (p)-[:HAS_MEDIA]->(m)
        """,
        media_id=media["id"],
        post_id=post_id,
    )


def get_media_for_post(post_id: str) -> list[dict]:
    """Returns all Media nodes linked to a Post via HAS_MEDIA."""
    with get_driver().session() as s:
        result = s.run(
            "MATCH (p:Post {id: $post_id})-[:HAS_MEDIA]->(m:Media) RETURN m",
            post_id=post_id,
        )
        return [_node_to_dict(record["m"]) for record in result]


def get_media_node(media_id: str) -> dict:
    """Retrieves a Media node from the graph by ID."""
    with get_driver().session() as s:
        result = s.run("MATCH (m:Media {id: $id}) RETURN m", id=media_id)
        record = result.single()
        if not record:
            raise ValueError(f"Media with id {media_id} not found")
        return _node_to_dict(record["m"])


def update_media_status(media_id: str, status: str) -> None:
    """Updates the processing status of a Media node."""
    with get_driver().session() as s:
        s.execute_write(_update_media_status_tx, media_id, status)


def _update_media_status_tx(tx, media_id: str, status: str) -> None:
    now = _now_str()
    tx.run(
        "MATCH (m:Media {id: $media_id}) SET m.status = $status, m.updated_at = $updated_at",
        media_id=media_id,
        status=status,
        updated_at=now,
    )


def all_media_processed_for_post(post_id: str) -> bool:
    """Returns True if no PENDING media remains for the post."""
    with get_driver().session() as s:
        return s.execute_read(_all_media_processed_for_post_tx, post_id)


def _all_media_processed_for_post_tx(tx, post_id: str) -> bool:
    result = tx.run(
        """
        MATCH (p:Post {id: $post_id})-[:HAS_MEDIA]->(m:Media)
        WHERE m.status = 'PENDING'
        RETURN count(m) AS pending_count
        """,
        post_id=post_id,
    )
    record = result.single()
    return record is not None and record["pending_count"] == 0


# ─── Post Operations ──────────────────────────────────────────────────────────

_INDEXES = [
    "CREATE INDEX ON :Post(id)",
    "CREATE INDEX ON :Post(url)",
    "CREATE INDEX ON :Query(id)",
    "CREATE INDEX ON :Evidence(id)",
    "CREATE INDEX ON :Media(id)",
]


def ensure_indexes() -> None:
    """Idempotently create Memgraph indexes. Call once at server startup."""
    with get_driver().session() as s:
        for idx in _INDEXES:
            try:
                s.run(idx)
            except Exception as e:
                logger.debug(f"Index skipped (already exists?): {e}")
    logger.info("Memgraph indexes ensured")


def upsert_post(post: dict) -> None:
    """Merge a Post node into Memgraph."""
    with get_driver().session() as s:
        s.execute_write(_upsert_post_tx, post)


def _upsert_post_tx(tx, post: dict) -> None:
    import json
    post_copy = post.copy()
    if "costs" in post_copy:
        post_copy["costs_json"] = json.dumps(post_copy.pop("costs"))
    else:
        post_copy["costs_json"] = "{}"
    
    # default if not present
    if "agent_start_time" not in post_copy:
        post_copy["agent_start_time"] = 0.0

    tx.run(
        """
        MERGE (p:Post {id: $id})
        SET p.url           = $url,
            p.title         = $title,
            p.content       = $content,
            p.status        = $status,
            p.justification = $justification,
            p.agent_start_time = $agent_start_time,
            p.costs_json    = $costs_json,
            p.created_at    = $created_at,
            p.updated_at    = $updated_at
        """,
        **post_copy,
    )


def get_post_node(post_id: str) -> dict:
    """Returns the Post node as a dict, raising ValueError if not found."""
    with get_driver().session() as s:
        result = s.run("MATCH (p:Post {id: $id}) RETURN p", id=post_id)
        record = result.single()
        if not record:
            raise ValueError(f"Post with id {post_id!r} not found")
        return _node_to_dict(record["p"])


def try_claim_post_for_judging(post_id: str) -> bool:
    """Atomically transitions the post from PENDING → JUDGING.

    Returns True only if THIS caller made the transition (i.e. it won the race
    and should publish PostCompletion). Returns False if another replica already
    claimed it — the caller must NOT publish PostCompletion in that case.

    This prevents multiple evidence_retrieval replicas from each publishing
    PostCompletion when they all finish processing evidence simultaneously.
    """
    with get_driver().session() as s:
        return s.execute_write(_try_claim_post_for_judging_tx, post_id)


def _try_claim_post_for_judging_tx(tx, post_id: str) -> bool:
    result = tx.run(
        """
        MATCH (p:Post {id: $post_id})
        WHERE p.status = 'TBD'
        SET p.status = 'JUDGING', p.updated_at = $now
        RETURN count(p) AS claimed
        """,
        post_id=post_id,
        now=_now_str(),
    ).single()
    return result is not None and result["claimed"] > 0


def update_post_verdict(post_id: str, verdict: str, justification: str) -> None:
    """Sets the final verdict and justification on a Post."""
    with get_driver().session() as s:
        s.execute_write(_update_post_verdict_tx, post_id, verdict, justification)


def _update_post_verdict_tx(tx, post_id: str, verdict: str, justification: str) -> None:
    tx.run(
        """
        MATCH (p:Post {id: $post_id})
        SET p.status        = $verdict,
            p.justification = $justification,
            p.updated_at    = $updated_at
        """,
        post_id=post_id,
        verdict=verdict,
        justification=justification,
        updated_at=_now_str(),
    )


def set_post_start_time(post_id: str, start_time: float) -> None:
    with get_driver().session() as s:
        s.execute_write(_set_post_start_time_tx, post_id, start_time)

def _set_post_start_time_tx(tx, post_id: str, start_time: float) -> None:
    tx.run(
        """
        MATCH (p:Post {id: $post_id})
        WHERE p.agent_start_time IS NULL OR p.agent_start_time = 0.0
        SET p.agent_start_time = $start_time
        """,
        post_id=post_id,
        start_time=start_time,
    )

def add_agent_cost(post_id: str, agent_name: str, cost: float) -> None:
    """Adds or updates the cost for a specific agent in the Post node."""
    with get_driver().session() as s:
        s.execute_write(_add_agent_cost_tx, post_id, agent_name, cost)

def _add_agent_cost_tx(tx, post_id: str, agent_name: str, cost: float) -> None:
    result = tx.run("MATCH (p:Post {id: $post_id}) RETURN p.costs_json AS costs_json", post_id=post_id).single()
    if not result:
        return
    import json
    costs_str = result["costs_json"]
    costs = json.loads(costs_str) if costs_str else {}
    costs[agent_name] = costs.get(agent_name, 0.0) + cost
    tx.run("MATCH (p:Post {id: $post_id}) SET p.costs_json = $costs_json", post_id=post_id, costs_json=json.dumps(costs))


def list_posts(limit: int = 100) -> list[dict]:
    """Returns recent Post nodes sorted newest-first."""
    with get_driver().session() as s:
        result = s.run(
            "MATCH (p:Post) RETURN p ORDER BY p.created_at DESC LIMIT $limit",
            limit=limit,
        )
        return [_node_to_dict(record["p"]) for record in result]


def delete_all_nodes() -> None:
    """Deletes every node and relationship in the graph. Use with caution."""
    with get_driver().session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    logger.info("All nodes and relationships deleted from graph")
