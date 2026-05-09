"use client";

import { useState, useEffect, useRef } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface SubmitResult {
  submission_id: string;
  url: string;
  message: string;
}

interface PostNode {
  id: string;
  url: string;
  title: string;
  content: string;
  status: string;
  justification: string;
  created_at: string;
  costs?: Record<string, number>;
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

// ─── Constants ────────────────────────────────────────────────────────────────

const FINAL_STATUSES = new Set(["VERIFIED", "REFUTED", "NEI"]);

const PIPELINE_STEPS = [
  {
    number: "01",
    title: "Post Creation",
    description:
      "The submitted URL is scraped and parsed into a structured Post node stored in Memgraph.",
  },
  {
    number: "02",
    title: "Query Generation",
    description:
      "Claims in the post are decomposed into targeted atomic search queries by an LLM agent.",
  },
  {
    number: "03",
    title: "Evidence Retrieval",
    description:
      "Each query is dispatched to Tavily search; results are stored as Evidence nodes linked to the post.",
  },
  {
    number: "04",
    title: "Media Verification",
    description:
      "Attached images are downloaded and AI-deepfake-checked by the media verification service.",
  },
  {
    number: "05",
    title: "Post Judge",
    description:
      "A judge–critic agent loop reviews all evidence and produces a VERIFIED / REFUTED / NEI verdict.",
  },
];

type InputMode = "url" | "social";
type StageStatus = "pending" | "active" | "done" | "skipped";

interface StageInfo {
  number: string;
  title: string;
  status: StageStatus;
  detail: string;
}

// ─── Social media platform detection ─────────────────────────────────────────

function detectPlatform(url: string): string | null {
  try {
    const { hostname } = new URL(url);
    if (/twitter\.com|x\.com/.test(hostname)) return "Twitter / X";
    if (/reddit\.com/.test(hostname)) return "Reddit";
    if (/facebook\.com|fb\.com/.test(hostname)) return "Facebook";
    if (/instagram\.com/.test(hostname)) return "Instagram";
    if (/tiktok\.com/.test(hostname)) return "TikTok";
    if (/youtube\.com|youtu\.be/.test(hostname)) return "YouTube";
    if (/linkedin\.com/.test(hostname)) return "LinkedIn";
  } catch {
    // invalid URL while typing
  }
  return null;
}

// ─── Stage computation ────────────────────────────────────────────────────────

function computeStages(details: PostDetails | null): StageInfo[] {
  if (!details) {
    return [
      { number: "01", title: "Post Creation", status: "active", detail: "Scraping URL content…" },
      { number: "02", title: "Query Generation", status: "pending", detail: "" },
      { number: "03", title: "Evidence Retrieval", status: "pending", detail: "" },
      { number: "04", title: "Media Verification", status: "pending", detail: "" },
      { number: "05", title: "Post Judge", status: "pending", detail: "" },
    ];
  }

  const { post, queries, evidence_by_query, media } = details;
  const isFinal = FINAL_STATUSES.has(post.status);
  const isJudging = post.status === "JUDGING";

  const totalEvidence = evidence_by_query.reduce((s, q) => s + q.evidence.length, 0);
  const completedEvidence = evidence_by_query.reduce(
    (s, q) => s + q.evidence.filter((e) => e.status === "COMPLETED").length,
    0
  );
  const completedQueries = queries.filter((q) => q.status === "COMPLETED").length;
  const totalMedia = media.length;
  const completedMedia = media.filter((m) => m.status !== "PENDING").length;

  const allQueriesDone = queries.length > 0 && completedQueries === queries.length;
  const allEvidenceDone = allQueriesDone && totalEvidence > 0 && completedEvidence === totalEvidence;

  const s1: StageInfo = {
    number: "01",
    title: "Post Creation",
    status: "done",
    detail: post.title
      ? `"${post.title.slice(0, 72)}${post.title.length > 72 ? "…" : ""}"`
      : "Content extracted",
  };

  let s2: StageInfo;
  if (queries.length === 0) {
    s2 = { number: "02", title: "Query Generation", status: "active", detail: "Decomposing claims…" };
  } else if (!allQueriesDone) {
    s2 = {
      number: "02",
      title: "Query Generation",
      status: "active",
      detail: `${completedQueries}/${queries.length} queries complete`,
    };
  } else {
    s2 = {
      number: "02",
      title: "Query Generation",
      status: "done",
      detail: `${queries.length} ${queries.length === 1 ? "query" : "queries"} generated`,
    };
  }

  let s3: StageInfo;
  if (!allQueriesDone) {
    s3 = { number: "03", title: "Evidence Retrieval", status: "pending", detail: "" };
  } else if (!allEvidenceDone) {
    s3 = {
      number: "03",
      title: "Evidence Retrieval",
      status: "active",
      detail:
        totalEvidence > 0
          ? `${completedEvidence}/${totalEvidence} items retrieved`
          : "Searching the web…",
    };
  } else {
    s3 = {
      number: "03",
      title: "Evidence Retrieval",
      status: "done",
      detail: `${totalEvidence} evidence ${totalEvidence === 1 ? "item" : "items"} found`,
    };
  }

  let s4: StageInfo;
  if (totalMedia === 0) {
    s4 = {
      number: "04",
      title: "Media Verification",
      status: allEvidenceDone ? "skipped" : "pending",
      detail: allEvidenceDone ? "No media attached" : "",
    };
  } else if (completedMedia < totalMedia) {
    s4 = {
      number: "04",
      title: "Media Verification",
      status: "active",
      detail: `${completedMedia}/${totalMedia} media verified`,
    };
  } else {
    s4 = {
      number: "04",
      title: "Media Verification",
      status: "done",
      detail: `${totalMedia} media ${totalMedia === 1 ? "item" : "items"} verified`,
    };
  }

  let s5: StageInfo;
  if (isFinal) {
    s5 = { number: "05", title: "Post Judge", status: "done", detail: post.status };
  } else if (isJudging) {
    s5 = { number: "05", title: "Post Judge", status: "active", detail: "Evaluating evidence…" };
  } else {
    s5 = { number: "05", title: "Post Judge", status: "pending", detail: "" };
  }

  return [s1, s2, s3, s4, s5];
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StageRow({ stage, isLast }: { stage: StageInfo; isLast: boolean }) {
  const isDone = stage.status === "done";
  const isActive = stage.status === "active";
  const isPending = stage.status === "pending";
  const isSkipped = stage.status === "skipped";

  const circleColor = isDone || isActive ? "#ff4f00" : "#c5c0b1";
  const circleBg = isDone ? "#ff4f00" : isSkipped ? "#eceae3" : "transparent";
  const lineColor = isDone ? "#ff4f00" : "#eceae3";

  return (
    <div style={{ display: "flex", gap: "16px" }}>
      {/* Indicator column */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          width: "36px",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: "36px",
            height: "36px",
            borderRadius: "50%",
            border: `2px solid ${circleColor}`,
            backgroundColor: circleBg,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          {isDone && (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path
                d="M2.5 7L5.5 10L11.5 4"
                stroke="#fffefb"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
          {isActive && (
            <div
              style={{
                width: "10px",
                height: "10px",
                borderRadius: "50%",
                backgroundColor: "#ff4f00",
                animation: "pulse 1.5s ease-in-out infinite",
              }}
            />
          )}
          {isPending && (
            <span
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "11px",
                fontWeight: 600,
                color: "#c5c0b1",
              }}
            >
              {stage.number}
            </span>
          )}
          {isSkipped && (
            <span
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "13px",
                fontWeight: 500,
                color: "#939084",
              }}
            >
              —
            </span>
          )}
        </div>

        {!isLast && (
          <div
            style={{
              flex: 1,
              width: "2px",
              minHeight: "28px",
              backgroundColor: lineColor,
              marginTop: "4px",
            }}
          />
        )}
      </div>

      {/* Content column */}
      <div
        style={{
          flex: 1,
          paddingTop: "6px",
          paddingBottom: isLast ? "0" : "28px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            marginBottom: stage.detail ? "4px" : "0",
          }}
        >
          <span
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "15px",
              fontWeight: 600,
              color: isPending ? "#939084" : "#201515",
            }}
          >
            {stage.title}
          </span>
          {isActive && (
            <span
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "11px",
                fontWeight: 600,
                color: "#ff4f00",
                textTransform: "uppercase",
                letterSpacing: "0.5px",
              }}
            >
              Running
            </span>
          )}
          {isSkipped && (
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
              Skipped
            </span>
          )}
        </div>
        {stage.detail && (
          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "13px",
              color: "#939084",
              margin: 0,
              lineHeight: 1.5,
            }}
          >
            {stage.detail}
          </p>
        )}
      </div>
    </div>
  );
}

function VerdictBadge({ status }: { status: string }) {
  const map: Record<string, { color: string; bg: string; border: string }> = {
    VERIFIED: { color: "#ff4f00", bg: "#fff5f0", border: "#ff4f00" },
    REFUTED: { color: "#201515", bg: "#eceae3", border: "#c5c0b1" },
    NEI: { color: "#939084", bg: "#fffefb", border: "#c5c0b1" },
  };
  const cfg = map[status] ?? { color: "#939084", bg: "#fffefb", border: "#c5c0b1" };
  return (
    <span
      style={{
        display: "inline-block",
        padding: "6px 14px",
        backgroundColor: cfg.bg,
        border: `1px solid ${cfg.border}`,
        borderRadius: "4px",
        fontFamily: "Inter, sans-serif",
        fontSize: "13px",
        fontWeight: 600,
        color: cfg.color,
        textTransform: "uppercase",
        letterSpacing: "0.5px",
      }}
    >
      {status === "NEI" ? "Not Enough Info" : status === "VERIFIED" ? "Verified" : "Refuted"}
    </span>
  );
}

// ─── Input field shared style helper ─────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "12px 16px",
  fontFamily: "Inter, sans-serif",
  fontSize: "15px",
  color: "#201515",
  backgroundColor: "#fffefb",
  border: "1px solid #c5c0b1",
  borderRadius: "5px",
  outline: "none",
};

function FocusInput({
  style,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      style={{ ...inputStyle, ...style }}
      onFocus={(e) => {
        e.currentTarget.style.borderColor = "#ff4f00";
      }}
      onBlur={(e) => {
        e.currentTarget.style.borderColor = "#c5c0b1";
      }}
      {...props}
    />
  );
}

// ─── Pipeline Tracker component ───────────────────────────────────────────────

function PipelineTracker({
  submittedUrl,
  onReset,
}: {
  submittedUrl: string;
  onReset: () => void;
}) {
  const [details, setDetails] = useState<PostDetails | null>(null);
  const postIdRef = useRef<string | null>(null);
  const activeRef = useRef(true);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    activeRef.current = true;
    postIdRef.current = null;
    setDetails(null);
    setElapsed(0);

    const startMs = Date.now();
    const timerInterval = setInterval(
      () => setElapsed(Math.floor((Date.now() - startMs) / 1000)),
      1000
    );

    async function doPoll() {
      if (!activeRef.current) return;
      try {
        if (!postIdRef.current) {
          const res = await fetch("/api/backend/posts");
          if (!res.ok) return;
          const posts: PostNode[] = await res.json();
          const found = posts.find((p) => p.url === submittedUrl);
          if (!found) return;
          postIdRef.current = found.id;
        }

        const res = await fetch(`/api/backend/posts/${postIdRef.current}`);
        if (!res.ok) return;
        const data: PostDetails = await res.json();
        if (!activeRef.current) return;
        setDetails(data);
        if (FINAL_STATUSES.has(data.post.status)) {
          activeRef.current = false;
          clearInterval(pollInterval);
          clearInterval(timerInterval);
        }
      } catch {
        // ignore transient network errors
      }
    }

    doPoll();
    const pollInterval = setInterval(doPoll, 3000);

    return () => {
      activeRef.current = false;
      clearInterval(pollInterval);
      clearInterval(timerInterval);
    };
  }, [submittedUrl]);

  const stages = computeStages(details);
  const isFinal = details ? FINAL_STATUSES.has(details.post.status) : false;
  const totalEvidenceCount = details
    ? details.evidence_by_query.reduce((s, q) => s + q.evidence.length, 0)
    : 0;

  return (
    <section
      style={{ borderBottom: "1px solid #c5c0b1", backgroundColor: "#fffefb" }}
    >
      <div
        style={{ maxWidth: "1200px", margin: "0 auto", padding: "64px 24px" }}
      >
        <div className="tracker-grid">
          {/* Left: stage timeline */}
          <div>
            <p
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "12px",
                fontWeight: 600,
                color: "#939084",
                textTransform: "uppercase",
                letterSpacing: "0.5px",
                marginBottom: "8px",
              }}
            >
              Pipeline Progress
            </p>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "40px",
              }}
            >
              <h2
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "28px",
                  fontWeight: 600,
                  color: "#201515",
                  letterSpacing: "-0.5px",
                  margin: 0,
                }}
              >
                {isFinal ? "Fact-check complete" : "Verifying claim…"}
              </h2>
              {!isFinal && (
                <span
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "13px",
                    color: "#939084",
                  }}
                >
                  {elapsed}s
                </span>
              )}
            </div>

            {stages.map((stage, i) => (
              <StageRow
                key={stage.number}
                stage={stage}
                isLast={i === stages.length - 1}
              />
            ))}
          </div>

          {/* Right: details panel */}
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {/* Submitted URL */}
            <div
              style={{
                border: "1px solid #c5c0b1",
                borderRadius: "8px",
                padding: "20px 24px",
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
                  marginBottom: "8px",
                }}
              >
                Submitted
              </p>
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "14px",
                  color: "#201515",
                  margin: 0,
                  wordBreak: "break-all",
                  lineHeight: 1.5,
                }}
              >
                {submittedUrl}
              </p>
            </div>

            {/* Verdict card */}
            {isFinal && details && (
              <div
                style={{
                  border: "1px solid #c5c0b1",
                  borderRadius: "8px",
                  padding: "24px",
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
                    marginBottom: "16px",
                  }}
                >
                  Verdict
                </p>
                <div style={{ marginBottom: "16px" }}>
                  <VerdictBadge status={details.post.status} />
                </div>
                {details.post.justification && (
                  <p
                    style={{
                      fontFamily: "Inter, sans-serif",
                      fontSize: "14px",
                      color: "#36342e",
                      lineHeight: 1.65,
                      margin: "0 0 16px",
                    }}
                  >
                    {details.post.justification}
                  </p>
                )}
                <div
                  style={{
                    display: "flex",
                    gap: "16px",
                    flexWrap: "wrap",
                    paddingTop: "12px",
                    borderTop: "1px solid #eceae3",
                  }}
                >
                  {details.queries.length > 0 && (
                    <span
                      style={{
                        fontFamily: "Inter, sans-serif",
                        fontSize: "13px",
                        color: "#939084",
                      }}
                    >
                      {details.queries.length} queries
                    </span>
                  )}
                  {totalEvidenceCount > 0 && (
                    <span
                      style={{
                        fontFamily: "Inter, sans-serif",
                        fontSize: "13px",
                        color: "#939084",
                      }}
                    >
                      {totalEvidenceCount} evidence items
                    </span>
                  )}
                  {elapsed > 0 && (
                    <span
                      style={{
                        fontFamily: "Inter, sans-serif",
                        fontSize: "13px",
                        color: "#939084",
                      }}
                    >
                      {elapsed}s total
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Evidence sources */}
            {isFinal && details && totalEvidenceCount > 0 && (
              <div
                style={{
                  border: "1px solid #c5c0b1",
                  borderRadius: "8px",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    padding: "14px 20px",
                    borderBottom: "1px solid #c5c0b1",
                    backgroundColor: "#eceae3",
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
                    Evidence Sources
                  </p>
                </div>
                <div
                  style={{
                    padding: "16px 20px",
                    display: "flex",
                    flexDirection: "column",
                    gap: "12px",
                    maxHeight: "220px",
                    overflowY: "auto",
                  }}
                >
                  {details.evidence_by_query
                    .flatMap((q) =>
                      q.evidence.filter((e) => e.status === "COMPLETED" && e.url)
                    )
                    .slice(0, 8)
                    .map((e) => (
                      <div key={e.id}>
                        <p
                          style={{
                            fontFamily: "Inter, sans-serif",
                            fontSize: "13px",
                            fontWeight: 500,
                            color: "#201515",
                            margin: "0 0 2px",
                            lineHeight: 1.3,
                          }}
                        >
                          {e.title || "Untitled source"}
                        </p>
                        <p
                          style={{
                            fontFamily: "Inter, sans-serif",
                            fontSize: "12px",
                            color: "#939084",
                            margin: 0,
                            wordBreak: "break-all",
                          }}
                        >
                          {e.url}
                        </p>
                      </div>
                    ))}
                </div>
              </div>
            )}

            {/* Loading hint when still finding */}
            {!details && (
              <div
                style={{
                  border: "1px solid #eceae3",
                  borderRadius: "8px",
                  padding: "20px 24px",
                  backgroundColor: "#eceae3",
                }}
              >
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "14px",
                    color: "#939084",
                    margin: 0,
                    lineHeight: 1.5,
                  }}
                >
                  Waiting for the post creation agent to scrape the URL. This
                  typically takes 10–30 seconds.
                </p>
              </div>
            )}

            <button
              onClick={onReset}
              style={{
                padding: "12px 24px",
                fontFamily: "Inter, sans-serif",
                fontSize: "16px",
                fontWeight: 600,
                color: "#fffefb",
                backgroundColor: "#201515",
                border: "1px solid #201515",
                borderRadius: "8px",
                cursor: "pointer",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                  "#c5c0b1";
                (e.currentTarget as HTMLButtonElement).style.color = "#201515";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor =
                  "#201515";
                (e.currentTarget as HTMLButtonElement).style.color = "#fffefb";
              }}
            >
              Check another claim
            </button>
          </div>
        </div>
      </div>

      <style jsx>{`
        .tracker-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 64px;
          align-items: start;
        }
        @media (max-width: 768px) {
          .tracker-grid {
            grid-template-columns: 1fr;
            gap: 40px;
          }
        }
        .pipeline-grid {
          grid-template-columns: repeat(5, 1fr);
        }
        @media (max-width: 1024px) {
          .pipeline-grid {
            grid-template-columns: repeat(3, 1fr);
          }
        }
        @media (max-width: 600px) {
          .pipeline-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function HomePage() {
  const [inputMode, setInputMode] = useState<InputMode>("url");
  const [urlValue, setUrlValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState<SubmitResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState<string | null>(null);
  const [resetHover, setResetHover] = useState(false);

  const detectedPlatform =
    inputMode === "social" ? detectPlatform(urlValue) : null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!urlValue.trim()) return;

    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch("/api/backend/posts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlValue.trim() }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }

      const data: SubmitResult = await res.json();
      setSubmitted(data);
      setUrlValue("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReset() {
    if (
      !confirm(
        "This will wipe ALL graph data and purge Kafka topics. Continue?"
      )
    )
      return;

    setResetting(true);
    setResetMsg(null);

    try {
      const res = await fetch("/api/backend/admin/reset", { method: "POST" });
      if (res.status === 204 || res.ok) {
        setResetMsg("Graph and Kafka topics have been reset successfully.");
      } else {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch (err) {
      setResetMsg(
        `Reset failed: ${err instanceof Error ? err.message : "Unknown error"}`
      );
    } finally {
      setResetting(false);
    }
  }

  function handleNewClaim() {
    setSubmitted(null);
    setError(null);
  }

  const placeholders: Record<InputMode, string> = {
    url: "https://snopes.com/fact-check/…",
    social: "https://x.com/user/status/…  or  https://reddit.com/r/…",
  };

  return (
    <div>
      {/* ── Hero / Submit ──────────────────────────────────────────────── */}
      <section
        style={{
          backgroundColor: "#fffefb",
          paddingTop: "80px",
          paddingBottom: "80px",
          borderBottom: "1px solid #c5c0b1",
          textAlign: "center",
        }}
      >
        <div style={{ maxWidth: "760px", margin: "0 auto", padding: "0 24px" }}>
          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "12px",
              fontWeight: 600,
              color: "#939084",
              textTransform: "uppercase",
              letterSpacing: "0.5px",
              marginBottom: "24px",
            }}
          >
            01 / Fact-Check Pipeline
          </p>

          <h1
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "clamp(40px, 6vw, 64px)",
              fontWeight: 500,
              lineHeight: 1.04,
              color: "#201515",
              margin: "0 0 24px",
            }}
          >
            Verify any claim
            <br />
            automatically
          </h1>

          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "18px",
              fontWeight: 400,
              lineHeight: 1.55,
              color: "#36342e",
              marginBottom: "40px",
              letterSpacing: "-0.16px",
            }}
          >
            Submit an article URL or social media post. Our five-stage
            multi-agent pipeline searches for evidence and returns a{" "}
            <span style={{ color: "#ff4f00", fontWeight: 500 }}>VERIFIED</span>,{" "}
            <span style={{ fontWeight: 500 }}>REFUTED</span>, or{" "}
            <span style={{ fontWeight: 500 }}>NEI</span> verdict.
          </p>

          {/* Mode toggle */}
          <div
            style={{
              display: "inline-flex",
              border: "1px solid #c5c0b1",
              borderRadius: "8px",
              overflow: "hidden",
              marginBottom: "24px",
              backgroundColor: "#eceae3",
            }}
          >
            {(["url", "social"] as InputMode[]).map((mode) => (
              <button
                key={mode}
                onClick={() => {
                  setInputMode(mode);
                  setUrlValue("");
                  setError(null);
                }}
                style={{
                  padding: "8px 20px",
                  fontFamily: "Inter, sans-serif",
                  fontSize: "14px",
                  fontWeight: 600,
                  color: inputMode === mode ? "#fffefb" : "#36342e",
                  backgroundColor: inputMode === mode ? "#201515" : "transparent",
                  border: "none",
                  cursor: "pointer",
                  borderRadius: inputMode === mode ? "6px" : "0",
                  margin: inputMode === mode ? "2px" : "0",
                  transition: "all 0.15s ease",
                }}
              >
                {mode === "url" ? "Article URL" : "Social Media Post"}
              </button>
            ))}
          </div>

          {/* Input form */}
          <form onSubmit={handleSubmit}>
            <div
              style={{
                display: "flex",
                gap: "0",
                maxWidth: "600px",
                margin: "0 auto 12px",
                border: "1px solid #c5c0b1",
                borderRadius: "8px",
                overflow: "hidden",
                backgroundColor: "#fffefb",
              }}
            >
              <input
                type="url"
                value={urlValue}
                onChange={(e) => setUrlValue(e.target.value)}
                placeholder={placeholders[inputMode]}
                required
                disabled={!!submitted}
                style={{
                  flex: 1,
                  padding: "14px 16px",
                  fontFamily: "Inter, sans-serif",
                  fontSize: "15px",
                  color: "#201515",
                  backgroundColor: "transparent",
                  border: "none",
                  outline: "none",
                  minWidth: 0,
                  opacity: submitted ? 0.5 : 1,
                }}
                onFocus={(e) => {
                  (
                    e.currentTarget.parentElement as HTMLElement
                  ).style.borderColor = "#ff4f00";
                }}
                onBlur={(e) => {
                  (
                    e.currentTarget.parentElement as HTMLElement
                  ).style.borderColor = "#c5c0b1";
                }}
              />
              <button
                type="submit"
                disabled={submitting || !urlValue.trim() || !!submitted}
                style={{
                  padding: "14px 24px",
                  fontFamily: "Inter, sans-serif",
                  fontSize: "15px",
                  fontWeight: 600,
                  color: "#fffefb",
                  backgroundColor:
                    submitting || !urlValue.trim() || submitted
                      ? "#b5b2aa"
                      : "#ff4f00",
                  border: "none",
                  cursor:
                    submitting || !urlValue.trim() || submitted
                      ? "not-allowed"
                      : "pointer",
                  whiteSpace: "nowrap",
                }}
              >
                {submitting ? "Submitting…" : "Check claim"}
              </button>
            </div>

            {/* Platform detection hint */}
            {detectedPlatform && (
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "13px",
                  color: "#ff4f00",
                  fontWeight: 500,
                  margin: "0 0 0",
                }}
              >
                {detectedPlatform} post detected
              </p>
            )}

            {inputMode === "social" && !detectedPlatform && (
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "13px",
                  color: "#939084",
                  margin: "0 0 0",
                }}
              >
                Supports Twitter/X, Reddit, Facebook, Instagram, and more
              </p>
            )}
          </form>

          {/* Error */}
          {error && (
            <div
              style={{
                maxWidth: "600px",
                margin: "16px auto 0",
                padding: "14px 20px",
                backgroundColor: "#fffefb",
                border: "1px solid #c5c0b1",
                borderRadius: "8px",
                textAlign: "left",
              }}
            >
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "14px",
                  color: "#36342e",
                  margin: 0,
                }}
              >
                <span style={{ fontWeight: 600, color: "#201515" }}>
                  Error:
                </span>{" "}
                {error}
              </p>
            </div>
          )}

          {/* Submission confirmation (before pipeline tracker loads) */}
          {submitted && (
            <div
              style={{
                maxWidth: "600px",
                margin: "16px auto 0",
                padding: "14px 20px",
                backgroundColor: "#fffefb",
                border: "1px solid #c5c0b1",
                borderRadius: "8px",
                textAlign: "left",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "12px",
              }}
            >
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "14px",
                  color: "#36342e",
                  margin: 0,
                }}
              >
                <span style={{ fontWeight: 600, color: "#ff4f00" }}>
                  Queued.
                </span>{" "}
                Tracking pipeline progress below.
              </p>
              <button
                onClick={handleNewClaim}
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "13px",
                  fontWeight: 600,
                  color: "#36342e",
                  backgroundColor: "#eceae3",
                  border: "1px solid #c5c0b1",
                  borderRadius: "4px",
                  padding: "6px 12px",
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                }}
              >
                New claim
              </button>
            </div>
          )}
        </div>
      </section>

      {/* ── Pipeline Tracker ──────────────────────────────────────────────── */}
      {submitted && (
        <PipelineTracker
          submittedUrl={submitted.url}
          onReset={handleNewClaim}
        />
      )}

      {/* ── How it works ──────────────────────────────────────────────────── */}
      <section
        style={{ maxWidth: "1200px", margin: "0 auto", padding: "80px 24px" }}
      >
        <p
          style={{
            fontFamily: "Inter, sans-serif",
            fontSize: "12px",
            fontWeight: 600,
            color: "#939084",
            textTransform: "uppercase",
            letterSpacing: "0.5px",
            marginBottom: "16px",
          }}
        >
          02 / How it works
        </p>
        <h2
          style={{
            fontFamily: "Inter, sans-serif",
            fontSize: "36px",
            fontWeight: 500,
            color: "#201515",
            letterSpacing: "-1px",
            marginBottom: "48px",
          }}
        >
          Five-stage verification pipeline
        </h2>

        <div
          className="pipeline-grid"
          style={{
            display: "grid",
            gap: "1px",
            backgroundColor: "#c5c0b1",
            border: "1px solid #c5c0b1",
            borderRadius: "8px",
            overflow: "hidden",
          }}
        >
          {PIPELINE_STEPS.map((step) => (
            <div
              key={step.number}
              style={{ backgroundColor: "#fffefb", padding: "32px" }}
            >
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "#ff4f00",
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                  marginBottom: "12px",
                }}
              >
                {step.number}
              </p>
              <h3
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "18px",
                  fontWeight: 600,
                  color: "#201515",
                  marginBottom: "10px",
                }}
              >
                {step.title}
              </h3>
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "15px",
                  color: "#36342e",
                  lineHeight: 1.5,
                  margin: 0,
                }}
              >
                {step.description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Verdict Key ───────────────────────────────────────────────────── */}
      <section
        style={{
          borderTop: "1px solid #c5c0b1",
          borderBottom: "1px solid #c5c0b1",
          backgroundColor: "#eceae3",
        }}
      >
        <div
          style={{
            maxWidth: "1200px",
            margin: "0 auto",
            padding: "64px 24px",
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
              marginBottom: "16px",
            }}
          >
            03 / Verdicts
          </p>
          <h2
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "32px",
              fontWeight: 500,
              color: "#201515",
              marginBottom: "40px",
            }}
          >
            Three possible outcomes
          </h2>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: "16px",
            }}
          >
            {[
              {
                label: "VERIFIED",
                accent: "#ff4f00",
                desc: "Evidence supports the claim. The pipeline found credible sources corroborating the assertion.",
              },
              {
                label: "REFUTED",
                accent: "#36342e",
                desc: "Evidence contradicts the claim. Sources found actively dispute the assertion made.",
              },
              {
                label: "NEI",
                accent: "#939084",
                desc: "Not Enough Information. The pipeline couldn't find sufficient evidence to confirm or deny.",
              },
            ].map(({ label, accent, desc }) => (
              <div
                key={label}
                style={{
                  backgroundColor: "#fffefb",
                  border: "1px solid #c5c0b1",
                  borderRadius: "8px",
                  padding: "24px",
                }}
              >
                <span
                  style={{
                    display: "inline-block",
                    fontFamily: "Inter, sans-serif",
                    fontSize: "12px",
                    fontWeight: 600,
                    color: accent,
                    textTransform: "uppercase",
                    letterSpacing: "0.5px",
                    marginBottom: "12px",
                    padding: "4px 10px",
                    border: `1px solid ${accent === "#ff4f00" ? "#ff4f00" : "#c5c0b1"}`,
                    borderRadius: "4px",
                  }}
                >
                  {label}
                </span>
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "15px",
                    color: "#36342e",
                    lineHeight: 1.5,
                    margin: 0,
                  }}
                >
                  {desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Admin Reset ───────────────────────────────────────────────────── */}
      <section
        style={{ maxWidth: "1200px", margin: "0 auto", padding: "80px 24px" }}
      >
        <div
          style={{
            border: "1px solid #c5c0b1",
            borderRadius: "8px",
            padding: "40px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: "32px",
              flexWrap: "wrap",
            }}
          >
            <div style={{ flex: 1, minWidth: "240px" }}>
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
                Admin
              </p>
              <h2
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "24px",
                  fontWeight: 600,
                  color: "#201515",
                  letterSpacing: "-0.48px",
                  marginBottom: "12px",
                }}
              >
                Reset pipeline
              </h2>
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "15px",
                  color: "#36342e",
                  lineHeight: 1.5,
                  margin: 0,
                }}
              >
                Wipes all Post, Query, Evidence, and Media nodes from Memgraph and
                purges all Kafka topic messages. Use during development to clear
                stale data.
              </p>
            </div>

            <button
              onClick={handleReset}
              disabled={resetting}
              onMouseEnter={() => setResetHover(true)}
              onMouseLeave={() => setResetHover(false)}
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "16px",
                fontWeight: 600,
                color: resetting ? "#fffefb" : resetHover ? "#201515" : "#fffefb",
                backgroundColor: resetting ? "#b5b2aa" : resetHover ? "#c5c0b1" : "#201515",
                padding: "12px 24px",
                border: `1px solid ${resetting ? "#b5b2aa" : "#201515"}`,
                borderRadius: "8px",
                cursor: resetting ? "not-allowed" : "pointer",
                whiteSpace: "nowrap",
                alignSelf: "flex-start",
              }}
            >
              {resetting ? "Resetting…" : "Reset graph & Kafka"}
            </button>
          </div>

          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "14px",
              color: resetMsg?.startsWith("Reset failed") ? "#36342e" : "#ff4f00",
              fontWeight: 500,
              margin: "16px 0 0",
              minHeight: "20px",
            }}
          >
            {resetMsg ?? ""}
          </p>
        </div>
      </section>
    </div>
  );
}
