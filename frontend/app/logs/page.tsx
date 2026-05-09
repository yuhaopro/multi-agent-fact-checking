"use client";

import { useState, useEffect, useRef } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface PostNode {
  id: string;
  url: string;
  title: string;
  content: string;
  status: string;
  justification: string;
  created_at: string;
}

interface QueryNode {
  id: string;
  query_text: string;
  status: string;
}

interface EvidenceNode {
  id: string;
  title: string;
  url: string;
  status: string;
}

interface EvidenceByQuery {
  query_text: string;
  evidence: EvidenceNode[];
}

interface MediaNode {
  id: string;
  url: string;
  type: string;
  status: string;
  is_ai_generated: boolean;
}

interface PostDetails {
  post: PostNode;
  queries: QueryNode[];
  evidence_by_query: EvidenceByQuery[];
  media: MediaNode[];
}

type AgentTab =
  | "post-creation"
  | "query-generation"
  | "evidence-retrieval"
  | "media-verification"
  | "post-judge";

interface ChatMessage {
  id: string;
  role: "input" | "output" | "info";
  label: string;
  content: string;
  meta?: string;
  status?: "pending" | "done" | "skipped";
}

// ─── Constants ────────────────────────────────────────────────────────────────

const FINAL_STATUSES = new Set(["VERIFIED", "REFUTED", "NEI"]);

const AGENT_TABS: { id: AgentTab; label: string; desc: string }[] = [
  {
    id: "post-creation",
    label: "Post Creation",
    desc: "Scrapes the submitted URL and creates a Post node in the graph.",
  },
  {
    id: "query-generation",
    label: "Query Generation",
    desc: "Decomposes the claim into atomic search queries via a judge–critic loop.",
  },
  {
    id: "evidence-retrieval",
    label: "Evidence Retrieval",
    desc: "Runs each query through Tavily and stores retrieved evidence.",
  },
  {
    id: "media-verification",
    label: "Media Verification",
    desc: "Downloads attached images and checks for AI-generated content.",
  },
  {
    id: "post-judge",
    label: "Post Judge",
    desc: "Reviews all evidence and produces a VERIFIED / REFUTED / NEI verdict.",
  },
];

// ─── Message builder ──────────────────────────────────────────────────────────

function buildMessages(agent: AgentTab, details: PostDetails): ChatMessage[] {
  const { post, queries, evidence_by_query, media } = details;
  const msgs: ChatMessage[] = [];

  if (agent === "post-creation") {
    msgs.push({
      id: "pc-url",
      role: "input",
      label: "URL Submitted",
      content: post.url || "(no URL — eval claim)",
    });
    if (post.title || post.content) {
      msgs.push({
        id: "pc-extracted",
        role: "output",
        label: "Content Extracted",
        content: [
          post.title ? `${post.title}` : null,
          post.content
            ? post.content.slice(0, 400) + (post.content.length > 400 ? "…" : "")
            : null,
        ]
          .filter(Boolean)
          .join("\n\n"),
        status: "done",
      });
    } else {
      msgs.push({
        id: "pc-scraping",
        role: "info",
        label: "Scraping",
        content: "Fetching and parsing URL content…",
        status: "pending",
      });
    }
  }

  if (agent === "query-generation") {
    msgs.push({
      id: "qg-claim",
      role: "input",
      label: "Claim Received",
      content:
        post.content?.slice(0, 500) +
          (post.content && post.content.length > 500 ? "…" : "") ||
        post.title ||
        "(empty)",
    });

    if (queries.length === 0) {
      msgs.push({
        id: "qg-generating",
        role: "info",
        label: "Processing",
        content: "Decomposing claim into atomic search queries…",
        status: "pending",
      });
    } else {
      queries.forEach((q, i) => {
        msgs.push({
          id: `qg-q-${q.id}`,
          role: "output",
          label: `Query ${i + 1} of ${queries.length}`,
          content: q.query_text,
          status: q.status === "COMPLETED" ? "done" : "pending",
        });
      });

      const allDone =
        queries.length > 0 &&
        queries.every((q) => q.status === "COMPLETED");
      msgs.push({
        id: "qg-critic",
        role: "info",
        label: "Critic",
        content: allDone
          ? `Critic approved all ${queries.length} ${queries.length === 1 ? "query" : "queries"} — forwarding to evidence retrieval.`
          : `Critic reviewing ${queries.length} ${queries.length === 1 ? "query" : "queries"}…`,
        status: allDone ? "done" : "pending",
      });
    }
  }

  if (agent === "evidence-retrieval") {
    const queryStatusMap = new Map(queries.map((q) => [q.query_text, q.status]));

    if (queries.length === 0) {
      msgs.push({
        id: "er-wait",
        role: "info",
        label: "Waiting",
        content: "Waiting for query generation to complete…",
        status: "pending",
      });
    } else if (evidence_by_query.length === 0) {
      msgs.push({
        id: "er-searching",
        role: "info",
        label: "Searching",
        content: "Dispatching queries to Google Search…",
        status: "pending",
      });
      msgs.push({
        id: "er-ratelimit-note",
        role: "info",
        label: "Rate limiting",
        content: "2s delay between queries — 60s backoff on 429.",
        status: "pending",
      });
    } else {
      const stillPending = evidence_by_query.filter(
        (eq) => eq.evidence.length === 0 && queryStatusMap.get(eq.query_text) !== "COMPLETED"
      );
      const completedQueries = evidence_by_query.filter(
        (eq) => eq.evidence.length > 0 || queryStatusMap.get(eq.query_text) === "COMPLETED"
      );

      if (stillPending.length > 0) {
        msgs.push({
          id: "er-ratelimit-active",
          role: "info",
          label: "Rate limiting",
          content: `2s delay between queries — ${completedQueries.length}/${evidence_by_query.length} dispatched. 60s backoff on 429.`,
          status: "pending",
        });
      }

      evidence_by_query.forEach((eq, qi) => {
        msgs.push({
          id: `er-query-${qi}`,
          role: "input",
          label: `Query ${qi + 1}`,
          content: eq.query_text,
        });

        const queryDone = queryStatusMap.get(eq.query_text) === "COMPLETED";

        if (eq.evidence.length === 0) {
          msgs.push({
            id: `er-waiting-${qi}`,
            role: "info",
            label: queryDone ? "No Results" : "Searching",
            content: queryDone ? "Search completed — no results found." : "Retrieving results…",
            status: queryDone ? "done" : "pending",
          });
        } else {
          eq.evidence.forEach((e, ei) => {
            msgs.push({
              id: `er-ev-${qi}-${ei}`,
              role: "output",
              label: "Evidence Found",
              content: e.title || "Untitled source",
              meta: e.url,
              status: e.status === "COMPLETED" ? "done" : "pending",
            });
          });
        }
      });
    }
  }

  if (agent === "media-verification") {
    if (media.length === 0) {
      msgs.push({
        id: "mv-none",
        role: "info",
        label: "No Media",
        content: "No images attached to this post — media verification skipped.",
        status: "skipped",
      });
    } else {
      media.forEach((m, i) => {
        msgs.push({
          id: `mv-in-${i}`,
          role: "input",
          label: `${m.type} Received`,
          content: m.url,
        });
        msgs.push({
          id: `mv-out-${i}`,
          role: "output",
          label: "Verification Result",
          content:
            m.status === "PENDING"
              ? "Checking for AI-generated content…"
              : m.is_ai_generated
              ? "Likely AI-generated — flagged."
              : "No AI manipulation detected.",
          status: m.status === "PENDING" ? "pending" : "done",
        });
      });
    }
  }

  if (agent === "post-judge") {
    const totalEvidence = evidence_by_query.reduce(
      (s, q) => s + q.evidence.length,
      0
    );

    if (totalEvidence === 0) {
      msgs.push({
        id: "pj-wait",
        role: "info",
        label: "Waiting",
        content: "Waiting for evidence retrieval to complete…",
        status: "pending",
      });
    } else {
      msgs.push({
        id: "pj-package",
        role: "input",
        label: "Evidence Package",
        content: `${totalEvidence} evidence item${totalEvidence === 1 ? "" : "s"} across ${queries.length} ${queries.length === 1 ? "query" : "queries"} ready for evaluation.`,
      });

      if (FINAL_STATUSES.has(post.status)) {
        msgs.push({
          id: "pj-verdict",
          role: "output",
          label: `Verdict — ${post.status}`,
          content: post.justification || "No justification recorded.",
          status: "done",
        });
      } else if (post.status === "JUDGING") {
        msgs.push({
          id: "pj-judging",
          role: "info",
          label: "Judge–Critic Loop",
          content: "Deliberating over evidence — verdict pending…",
          status: "pending",
        });
      } else {
        msgs.push({
          id: "pj-pending",
          role: "info",
          label: "Pending",
          content: "Awaiting completion of earlier pipeline stages…",
          status: "pending",
        });
      }
    }
  }

  return msgs;
}

// ─── ChatBubble ───────────────────────────────────────────────────────────────

function ChatBubble({ msg }: { msg: ChatMessage }) {
  const isInput = msg.role === "input";
  const isOutput = msg.role === "output";
  const isInfo = msg.role === "info";
  const isPending = msg.status === "pending";
  const isSkipped = msg.status === "skipped";

  if (isInfo) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          marginBottom: "20px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            padding: "8px 16px",
            backgroundColor: "#eceae3",
            border: "1px solid #c5c0b1",
            borderRadius: "20px",
            opacity: isSkipped ? 0.6 : 1,
          }}
        >
          {isPending && (
            <span
              style={{
                width: "7px",
                height: "7px",
                borderRadius: "50%",
                backgroundColor: "#ff4f00",
                flexShrink: 0,
                animation: "pulse 1.5s ease-in-out infinite",
              }}
            />
          )}
          {msg.status === "done" && (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path
                d="M2 6L5 9L10 3"
                stroke="#ff4f00"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
          <span
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "12px",
              fontWeight: 500,
              color: "#36342e",
            }}
          >
            {msg.content}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: isInput ? "flex-start" : "flex-end",
        marginBottom: "20px",
        gap: "4px",
      }}
    >
      <span
        style={{
          fontFamily: "Inter, sans-serif",
          fontSize: "11px",
          fontWeight: 600,
          color: "#939084",
          textTransform: "uppercase",
          letterSpacing: "0.5px",
          paddingLeft: isInput ? "4px" : undefined,
          paddingRight: isOutput ? "4px" : undefined,
        }}
      >
        {msg.label}
      </span>

      <div
        style={{
          maxWidth: "72%",
          padding: "12px 16px",
          borderRadius: isInput
            ? "4px 16px 16px 16px"
            : "16px 4px 16px 16px",
          backgroundColor: isInput ? "#fffefb" : "#201515",
          border: isInput ? "1px solid #c5c0b1" : "none",
        }}
      >
        {isPending && (
          <span
            style={{
              display: "inline-block",
              width: "7px",
              height: "7px",
              borderRadius: "50%",
              backgroundColor: isInput ? "#ff4f00" : "#fffefb",
              marginRight: "8px",
              verticalAlign: "middle",
              animation: "pulse 1.5s ease-in-out infinite",
            }}
          />
        )}
        <span
          style={{
            fontFamily: "Inter, sans-serif",
            fontSize: "14px",
            lineHeight: 1.6,
            color: isInput ? "#201515" : "#fffefb",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {msg.content}
        </span>
        {msg.meta && (
          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "11px",
              color: isInput ? "#939084" : "#b5b2aa",
              margin: "6px 0 0",
              wordBreak: "break-all",
              lineHeight: 1.4,
            }}
          >
            {msg.meta}
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Safe hostname helper ─────────────────────────────────────────────────────

function safeHostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url.slice(0, 40) || "—";
  }
}

// ─── Verdict colour ───────────────────────────────────────────────────────────

function statusColor(status: string): string {
  if (FINAL_STATUSES.has(status)) return "#ff4f00";
  if (status === "JUDGING") return "#36342e";
  return "#939084";
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function LogsPage() {
  const [posts, setPosts] = useState<PostNode[]>([]);
  const [loadingPosts, setLoadingPosts] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [details, setDetails] = useState<PostDetails | null>(null);
  const [activeAgent, setActiveAgent] = useState<AgentTab>("post-creation");
  const activeRef = useRef(true);

  // Load post list once
  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/backend/posts");
        if (res.ok) {
          const data: PostNode[] = await res.json();
          setPosts(data);
          if (data.length > 0) setSelectedId(data[0].id);
        }
      } finally {
        setLoadingPosts(false);
      }
    }
    load();
  }, []);

  // Poll selected post details
  useEffect(() => {
    if (!selectedId) return;
    activeRef.current = true;
    setDetails(null);

    async function doPoll() {
      if (!activeRef.current) return;
      try {
        const res = await fetch(`/api/backend/posts/${selectedId}`);
        if (!res.ok) return;
        const data: PostDetails = await res.json();
        if (!activeRef.current) return;
        setDetails(data);
        if (FINAL_STATUSES.has(data.post.status)) {
          activeRef.current = false;
          clearInterval(interval);
        }
      } catch {
        // ignore transient errors
      }
    }

    doPoll();
    const interval = setInterval(doPoll, 3000);
    return () => {
      activeRef.current = false;
      clearInterval(interval);
    };
  }, [selectedId]);


  const messages = details ? buildMessages(activeAgent, details) : [];
  const isFinal = details ? FINAL_STATUSES.has(details.post.status) : false;
  const activeTabInfo = AGENT_TABS.find((t) => t.id === activeAgent)!;

  return (
    <div>
      {/* ── Page header ───────────────────────────────────────────────────── */}
      <section
        style={{
          borderBottom: "1px solid #c5c0b1",
          backgroundColor: "#fffefb",
          padding: "64px 24px 0",
        }}
      >
        <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "12px",
              fontWeight: 600,
              color: "#939084",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              marginBottom: "12px",
            }}
          >
            Agent Logs
          </p>
          <h1
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "clamp(32px, 5vw, 48px)",
              fontWeight: 500,
              lineHeight: 1.04,
              color: "#201515",
              marginBottom: "32px",
            }}
          >
            Pipeline conversations
          </h1>

          {/* Agent sub-tabs */}
          <nav style={{ display: "flex", overflowX: "auto" }}>
            {AGENT_TABS.map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setActiveAgent(id)}
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "15px",
                  fontWeight: 500,
                  color: "#201515",
                  padding: "12px 16px",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                  boxShadow:
                    activeAgent === id
                      ? "rgb(255, 79, 0) 0px -4px 0px 0px inset"
                      : "none",
                }}
                onMouseEnter={(e) => {
                  if (activeAgent !== id)
                    (e.currentTarget as HTMLButtonElement).style.boxShadow =
                      "rgb(197, 192, 177) 0px -4px 0px 0px inset";
                }}
                onMouseLeave={(e) => {
                  if (activeAgent !== id)
                    (e.currentTarget as HTMLButtonElement).style.boxShadow =
                      "none";
                }}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </section>

      {/* ── Body ──────────────────────────────────────────────────────────── */}
      <section
        style={{ maxWidth: "1200px", margin: "0 auto", padding: "48px 24px" }}
      >
        <div className="logs-grid">
          {/* ── Post list ─────────────────────────────────────────────────── */}
          <div
            style={{
              border: "1px solid #c5c0b1",
              borderRadius: "8px",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div
              style={{
                padding: "14px 20px",
                borderBottom: "1px solid #c5c0b1",
                backgroundColor: "#eceae3",
                flexShrink: 0,
              }}
            >
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "#939084",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                  margin: 0,
                }}
              >
                Posts {posts.length > 0 ? `(${posts.length})` : ""}
              </p>
            </div>

            <div style={{ overflowY: "auto", flex: 1 }}>
              {loadingPosts ? (
                <p
                  style={{
                    padding: "20px",
                    fontFamily: "Inter, sans-serif",
                    fontSize: "14px",
                    color: "#939084",
                    margin: 0,
                  }}
                >
                  Loading…
                </p>
              ) : posts.length === 0 ? (
                <p
                  style={{
                    padding: "20px",
                    fontFamily: "Inter, sans-serif",
                    fontSize: "14px",
                    color: "#939084",
                    margin: 0,
                    lineHeight: 1.5,
                  }}
                >
                  No posts yet.
                  <br />
                  Submit a claim on the dashboard first.
                </p>
              ) : (
                posts.map((post) => {
                  const selected = post.id === selectedId;
                  return (
                    <button
                      key={post.id}
                      onClick={() => setSelectedId(post.id)}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        padding: "14px 18px",
                        backgroundColor: selected ? "#fff5f0" : "#fffefb",
                        border: "none",
                        borderLeft: selected
                          ? "3px solid #ff4f00"
                          : "3px solid transparent",
                        borderBottom: "1px solid #eceae3",
                        cursor: "pointer",
                      }}
                    >
                      <p
                        style={{
                          fontFamily: "Inter, sans-serif",
                          fontSize: "13px",
                          fontWeight: 600,
                          color: "#201515",
                          margin: "0 0 3px",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {post.title || safeHostname(post.url)}
                      </p>
                      <p
                        style={{
                          fontFamily: "Inter, sans-serif",
                          fontSize: "11px",
                          color: "#939084",
                          margin: "0 0 5px",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {post.url || "Eval claim"}
                      </p>
                      <span
                        style={{
                          fontFamily: "Inter, sans-serif",
                          fontSize: "11px",
                          fontWeight: 600,
                          color: statusColor(post.status),
                          textTransform: "uppercase",
                          letterSpacing: "0.5px",
                        }}
                      >
                        {post.status}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* ── Chat panel ────────────────────────────────────────────────── */}
          <div
            style={{
              border: "1px solid #c5c0b1",
              borderRadius: "8px",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {/* Chat header */}
            <div
              style={{
                padding: "14px 20px",
                borderBottom: "1px solid #c5c0b1",
                backgroundColor: "#eceae3",
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: "4px",
                }}
              >
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "13px",
                    fontWeight: 600,
                    color: "#201515",
                    margin: 0,
                  }}
                >
                  {activeTabInfo.label}
                </p>
                {details && !isFinal && (
                  <span
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "5px",
                      fontFamily: "Inter, sans-serif",
                      fontSize: "11px",
                      fontWeight: 600,
                      color: "#ff4f00",
                      textTransform: "uppercase",
                      letterSpacing: "0.5px",
                    }}
                  >
                    <span
                      style={{
                        width: "6px",
                        height: "6px",
                        borderRadius: "50%",
                        backgroundColor: "#ff4f00",
                        display: "inline-block",
                        animation: "pulse 1.5s ease-in-out infinite",
                      }}
                    />
                    Live
                  </span>
                )}
                {isFinal && (
                  <span
                    style={{
                      fontFamily: "Inter, sans-serif",
                      fontSize: "11px",
                      fontWeight: 600,
                      color: "#939084",
                      textTransform: "uppercase",
                      letterSpacing: "0.5px",
                    }}
                  >
                    Complete
                  </span>
                )}
              </div>
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "12px",
                  color: "#939084",
                  margin: 0,
                }}
              >
                {activeTabInfo.desc}
              </p>
            </div>

            {/* Messages */}
            <div
              style={{
                flex: 1,
                padding: "24px",
                overflowY: "auto",
                minHeight: "440px",
                maxHeight: "560px",
                backgroundColor: "#fffefb",
              }}
            >
              {!selectedId ? (
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "14px",
                    color: "#939084",
                    textAlign: "center",
                    marginTop: "60px",
                  }}
                >
                  Select a post from the list to view its agent conversation.
                </p>
              ) : !details ? (
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "14px",
                    color: "#939084",
                    textAlign: "center",
                    marginTop: "60px",
                  }}
                >
                  Loading…
                </p>
              ) : messages.length === 0 ? (
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "14px",
                    color: "#939084",
                    textAlign: "center",
                    marginTop: "60px",
                  }}
                >
                  No activity yet for this agent.
                </p>
              ) : (
                <>
                  {messages.map((msg) => (
                    <ChatBubble key={msg.id} msg={msg} />
                  ))}
                </>
              )}
            </div>

            {/* Footer: selected post info */}
            {details && (
              <div
                style={{
                  padding: "10px 20px",
                  borderTop: "1px solid #eceae3",
                  backgroundColor: "#fffefb",
                  flexShrink: 0,
                }}
              >
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "12px",
                    color: "#939084",
                    margin: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {details.post.title || safeHostname(details.post.url)} —{" "}
                  {details.queries.length} queries ·{" "}
                  {details.evidence_by_query.reduce(
                    (s, q) => s + q.evidence.length,
                    0
                  )}{" "}
                  evidence items ·{" "}
                  <span style={{ color: statusColor(details.post.status), fontWeight: 600 }}>
                    {details.post.status}
                  </span>
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      <style jsx>{`
        .logs-grid {
          display: grid;
          grid-template-columns: 260px 1fr;
          gap: 24px;
          align-items: start;
        }
        @media (max-width: 768px) {
          .logs-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
}
