"use client";

import { useState, useEffect, useRef, useCallback } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface EvalRecord {
  post_id: string;
  dataset_claim_id: string;
  truth_label: string;
  claim_text: string;
  snopes_url: string;
  system_verdict: string | null;
  correct: boolean | null;
  latency_seconds: number | null;
  costs: Record<string, number> | null;
}

interface EvalResults {
  total_submitted: number;
  completed: number;
  correct: number;
  accuracy: number;
  per_label: Record<string, { total: number; correct: number }>;
  records: EvalRecord[];
}

interface EvalSubmitResponse {
  post_id: string;
  dataset_claim_id: string;
  message: string;
}

interface BatchSubmitResponse {
  submitted: number;
  post_ids: string[];
  message: string;
}

interface MochegClaim {
  claim_id: string;
  claim_text: string;
  snopes_url: string;
  truth_label: string;
}

type Tab = "free-claim" | "mocheg-batch" | "results";
type TruthLabel = "supported" | "refuted" | "NEI" | "";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TRUTH_LABELS: TruthLabel[] = ["supported", "refuted", "NEI"];

const VERDICT_COLORS: Record<string, string> = {
  VERIFIED: "#ff4f00",
  REFUTED: "#36342e",
  NEI: "#939084",
};

function filterToPostIds(records: EvalRecord[], postIds: Set<string>): EvalRecord[] {
  return records.filter((r) => postIds.has(r.post_id));
}

function computeStats(records: EvalRecord[]) {
  const completed = records.filter((r) => r.system_verdict !== null);
  const correct = completed.filter((r) => r.correct).length;
  const accuracy = completed.length > 0 ? correct / completed.length : 0;
  const perLabel: Record<string, { total: number; correct: number }> = {};
  for (const r of completed) {
    const lbl = r.truth_label;
    if (!perLabel[lbl]) perLabel[lbl] = { total: 0, correct: 0 };
    perLabel[lbl].total++;
    if (r.correct) perLabel[lbl].correct++;
  }
  const avgLatency =
    completed.length > 0
      ? completed.reduce((s, r) => s + (r.latency_seconds ?? 0), 0) /
        completed.length
      : 0;
  const totalCost = records.reduce((s, r) => {
    if (!r.costs) return s;
    return s + Object.values(r.costs).reduce((a, v) => a + v, 0);
  }, 0);
  return { completed: completed.length, correct, accuracy, perLabel, avgLatency, totalCost };
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) {
    return (
      <span
        style={{
          fontFamily: "Inter, sans-serif",
          fontSize: "12px",
          fontWeight: 600,
          color: "#939084",
          textTransform: "uppercase",
          letterSpacing: "0.5px",
        }}
      >
        Pending…
      </span>
    );
  }
  const color = VERDICT_COLORS[verdict] ?? "#939084";
  return (
    <span
      style={{
        display: "inline-block",
        fontFamily: "Inter, sans-serif",
        fontSize: "12px",
        fontWeight: 600,
        color,
        textTransform: "uppercase",
        letterSpacing: "0.5px",
        padding: "3px 8px",
        border: `1px solid ${color === "#ff4f00" ? "#ff4f00" : "#c5c0b1"}`,
        borderRadius: "4px",
        backgroundColor: color === "#ff4f00" ? "#fff5f0" : "#fffefb",
      }}
    >
      {verdict}
    </span>
  );
}

function AccuracyBar({
  label,
  correct,
  total,
}: {
  label: string;
  correct: number;
  total: number;
}) {
  const pct = total > 0 ? Math.round((correct / total) * 100) : 0;
  return (
    <div style={{ marginBottom: "16px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: "6px",
        }}
      >
        <span
          style={{
            fontFamily: "Inter, sans-serif",
            fontSize: "14px",
            fontWeight: 500,
            color: "#36342e",
            textTransform: "capitalize",
          }}
        >
          {label}
        </span>
        <span
          style={{
            fontFamily: "Inter, sans-serif",
            fontSize: "14px",
            fontWeight: 600,
            color: "#201515",
          }}
        >
          {pct}% ({correct}/{total})
        </span>
      </div>
      <div
        style={{
          height: "6px",
          backgroundColor: "#eceae3",
          borderRadius: "3px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            backgroundColor: "#ff4f00",
            borderRadius: "3px",
            transition: "width 0.4s ease",
          }}
        />
      </div>
    </div>
  );
}

function StatCell({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub: string;
}) {
  return (
    <div style={{ backgroundColor: "#fffefb", padding: "24px", textAlign: "center" }}>
      <p
        style={{
          fontFamily: "Inter, sans-serif",
          fontSize: "32px",
          fontWeight: 500,
          color: "#201515",
          margin: "0 0 4px",
          lineHeight: 1,
        }}
      >
        {value}
      </p>
      <p
        style={{
          fontFamily: "Inter, sans-serif",
          fontSize: "12px",
          fontWeight: 600,
          color: "#939084",
          textTransform: "uppercase",
          letterSpacing: "0.5px",
          margin: "0 0 2px",
        }}
      >
        {label}
      </p>
      <p style={{ fontFamily: "Inter, sans-serif", fontSize: "12px", color: "#b5b2aa", margin: 0 }}>
        {sub}
      </p>
    </div>
  );
}

// ─── Shared input style ───────────────────────────────────────────────────────

const fieldLabel: React.CSSProperties = {
  display: "block",
  fontFamily: "Inter, sans-serif",
  fontSize: "14px",
  fontWeight: 600,
  color: "#201515",
  marginBottom: "8px",
};

const inputBase: React.CSSProperties = {
  width: "100%",
  padding: "10px 14px",
  fontFamily: "Inter, sans-serif",
  fontSize: "15px",
  color: "#201515",
  backgroundColor: "#fffefb",
  border: "1px solid #c5c0b1",
  borderRadius: "5px",
  outline: "none",
};

// ─── Batch progress panel ─────────────────────────────────────────────────────

function BatchProgress({
  postIds,
  total,
  onReset,
}: {
  postIds: string[];
  total: number;
  onReset: () => void;
}) {
  const postIdSet = useRef(new Set(postIds));
  const [batchRecords, setBatchRecords] = useState<EvalRecord[]>([]);
  const activeRef = useRef(true);

  useEffect(() => {
    activeRef.current = true;
    postIdSet.current = new Set(postIds);

    async function doPoll() {
      if (!activeRef.current) return;
      try {
        const res = await fetch("/api/backend/eval/results");
        if (!res.ok) return;
        const data: EvalResults = await res.json();
        const filtered = filterToPostIds(data.records, postIdSet.current);
        if (activeRef.current) {
          setBatchRecords(filtered);
          const done = filtered.filter((r) => r.system_verdict !== null).length;
          if (done >= postIds.length) {
            activeRef.current = false;
            clearInterval(interval);
          }
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
  }, [postIds]);

  const stats = computeStats(batchRecords);
  const isDone = stats.completed >= total;
  const pct = total > 0 ? Math.round((stats.completed / total) * 100) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
      {/* Progress header */}
      <div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "12px",
          }}
        >
          <p
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "15px",
              fontWeight: 600,
              color: "#201515",
              margin: 0,
            }}
          >
            {isDone ? "Batch complete" : `Running batch — ${stats.completed}/${total} verdicts in`}
          </p>
          <span
            style={{
              fontFamily: "Inter, sans-serif",
              fontSize: "13px",
              color: isDone ? "#ff4f00" : "#939084",
              fontWeight: isDone ? 600 : 400,
            }}
          >
            {pct}%
          </span>
        </div>
        <div
          style={{
            height: "6px",
            backgroundColor: "#eceae3",
            borderRadius: "3px",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              height: "100%",
              width: `${pct}%`,
              backgroundColor: isDone ? "#ff4f00" : "#201515",
              borderRadius: "3px",
              transition: "width 0.5s ease",
            }}
          />
        </div>
      </div>

      {/* Stats grid */}
      {stats.completed > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
            gap: "1px",
            border: "1px solid #c5c0b1",
            borderRadius: "8px",
            overflow: "hidden",
            backgroundColor: "#c5c0b1",
          }}
        >
          <StatCell label="Completed" value={stats.completed} sub={`of ${total}`} />
          <StatCell label="Correct" value={stats.correct} sub="accurate" />
          <StatCell
            label="Accuracy"
            value={`${(stats.accuracy * 100).toFixed(1)}%`}
            sub="overall"
          />
          <StatCell
            label="Avg Latency"
            value={`${stats.avgLatency.toFixed(1)}s`}
            sub="per claim"
          />
        </div>
      )}

      {/* Per-label bars */}
      {Object.keys(stats.perLabel).length > 0 && (
        <div
          style={{
            border: "1px solid #c5c0b1",
            borderRadius: "8px",
            padding: "24px",
            backgroundColor: "#fffefb",
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
              marginBottom: "20px",
            }}
          >
            Accuracy by label
          </p>
          {Object.entries(stats.perLabel).map(([label, { correct, total: t }]) => (
            <AccuracyBar key={label} label={label} correct={correct} total={t} />
          ))}
        </div>
      )}

      {/* Records table */}
      {batchRecords.length > 0 && (
        <div
          style={{ border: "1px solid #c5c0b1", borderRadius: "8px", overflow: "hidden" }}
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
              Batch records ({batchRecords.length})
            </p>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table
              style={{ width: "100%", borderCollapse: "collapse", fontFamily: "Inter, sans-serif", fontSize: "14px" }}
            >
              <thead>
                <tr style={{ backgroundColor: "#fffefb" }}>
                  {["Claim ID", "Claim", "Truth", "Verdict", "Correct", "Latency", "Cost"].map((col) => (
                    <th
                      key={col}
                      style={{
                        padding: "10px 16px",
                        textAlign: "left",
                        fontWeight: 600,
                        color: "#939084",
                        fontSize: "12px",
                        textTransform: "uppercase",
                        letterSpacing: "0.5px",
                        borderBottom: "1px solid #c5c0b1",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {batchRecords.map((r, idx) => (
                  <tr
                    key={r.post_id}
                    style={{
                      backgroundColor: idx % 2 === 0 ? "#fffefb" : "#fffdf9",
                      borderBottom: "1px solid #eceae3",
                    }}
                  >
                    <td style={{ padding: "10px 16px", color: "#36342e", fontWeight: 500, whiteSpace: "nowrap" }}>
                      {r.dataset_claim_id}
                    </td>
                    <td style={{ padding: "10px 16px", color: "#36342e", maxWidth: "260px" }}>
                      <span
                        style={{
                          display: "-webkit-box",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                          overflow: "hidden",
                        }}
                        title={r.claim_text}
                      >
                        {r.claim_text}
                      </span>
                    </td>
                    <td style={{ padding: "10px 16px", color: "#36342e", whiteSpace: "nowrap", textTransform: "capitalize" }}>
                      {r.truth_label}
                    </td>
                    <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                      <VerdictBadge verdict={r.system_verdict} />
                    </td>
                    <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                      {r.correct === null ? (
                        <span style={{ color: "#939084" }}>—</span>
                      ) : r.correct ? (
                        <span style={{ color: "#ff4f00", fontWeight: 600 }}>✓</span>
                      ) : (
                        <span style={{ color: "#36342e", fontWeight: 600 }}>✗</span>
                      )}
                    </td>
                    <td style={{ padding: "10px 16px", color: "#36342e", whiteSpace: "nowrap" }}>
                      {r.latency_seconds != null ? `${r.latency_seconds.toFixed(1)}s` : "—"}
                    </td>
                    <td style={{ padding: "10px 16px", color: "#36342e", whiteSpace: "nowrap" }}>
                      {r.costs && Object.keys(r.costs).length > 0 ? (
                        <span title={Object.entries(r.costs).map(([k, v]) => `${k}: $${v.toFixed(4)}`).join("\n")}>
                          ${Object.values(r.costs).reduce((a, v) => a + v, 0).toFixed(4)}
                        </span>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {isDone && (
        <button
          onClick={onReset}
          style={{
            padding: "12px 24px",
            fontFamily: "Inter, sans-serif",
            fontSize: "15px",
            fontWeight: 600,
            color: "#fffefb",
            backgroundColor: "#201515",
            border: "1px solid #201515",
            borderRadius: "8px",
            cursor: "pointer",
            alignSelf: "flex-start",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.backgroundColor = "#c5c0b1";
            (e.currentTarget as HTMLButtonElement).style.color = "#201515";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.backgroundColor = "#201515";
            (e.currentTarget as HTMLButtonElement).style.color = "#fffefb";
          }}
        >
          Run another batch
        </button>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function EvalPage() {
  const [activeTab, setActiveTab] = useState<Tab>("free-claim");

  // ── Free Claim state ──────────────────────────────────────────────────────
  const [claimText, setClaimText] = useState("");
  const [truthLabel, setTruthLabel] = useState<TruthLabel>("");
  const [submittingClaim, setSubmittingClaim] = useState(false);
  const [claimResult, setClaimResult] = useState<EvalSubmitResponse | null>(null);
  const [claimError, setClaimError] = useState<string | null>(null);

  // ── MOCHEG Batch state ────────────────────────────────────────────────────
  const [batchSize, setBatchSize] = useState(10);
  const [batchSeed, setBatchSeed] = useState(42);
  const [preview, setPreview] = useState<MochegClaim[] | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchResponse, setBatchResponse] = useState<BatchSubmitResponse | null>(null);
  const [batchError, setBatchError] = useState<string | null>(null);

  // ── Results state ─────────────────────────────────────────────────────────
  const [results, setResults] = useState<EvalResults | null>(null);
  const [loadingResults, setLoadingResults] = useState(false);
  const [resultsError, setResultsError] = useState<string | null>(null);

  const fetchResults = useCallback(async () => {
    setLoadingResults(true);
    setResultsError(null);
    try {
      const res = await fetch("/api/backend/eval/results");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResults(await res.json());
    } catch (err) {
      setResultsError(err instanceof Error ? err.message : "Failed to load results");
    } finally {
      setLoadingResults(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "results") fetchResults();
  }, [activeTab, fetchResults]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  async function handleClaimSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmittingClaim(true);
    setClaimResult(null);
    setClaimError(null);
    try {
      const res = await fetch("/api/backend/eval/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claim_text: claimText.trim(),
          truth_label: truthLabel || undefined,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      setClaimResult(await res.json());
      setClaimText("");
      setTruthLabel("");
    } catch (err) {
      setClaimError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setSubmittingClaim(false);
    }
  }

  async function handlePreview() {
    setLoadingPreview(true);
    setPreviewError(null);
    try {
      const res = await fetch(
        `/api/backend/eval/mocheg/claims?sample=${batchSize}&seed=${batchSeed}`
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      setPreview(await res.json());
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "Failed to load preview");
    } finally {
      setLoadingPreview(false);
    }
  }

  async function handleBatchRun() {
    setBatchRunning(true);
    setBatchResponse(null);
    setBatchError(null);
    try {
      const res = await fetch("/api/backend/eval/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample_size: batchSize, seed: batchSeed }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }
      setBatchResponse(await res.json());
    } catch (err) {
      setBatchError(err instanceof Error ? err.message : "Batch submission failed");
      setBatchRunning(false);
    }
  }

  function handleBatchReset() {
    setBatchResponse(null);
    setBatchRunning(false);
    setPreview(null);
  }

  // ─── Tab nav util ─────────────────────────────────────────────────────────

  const tabs: { id: Tab; label: string }[] = [
    { id: "free-claim", label: "Free Claim" },
    { id: "mocheg-batch", label: "MOCHEG Batch" },
    { id: "results", label: "Results" },
  ];

  // ─── Derived values ────────────────────────────────────────────────────────

  const avgLatency =
    results && results.completed > 0
      ? results.records
          .filter((r) => r.latency_seconds !== null)
          .reduce((s, r) => s + (r.latency_seconds ?? 0), 0) / results.completed
      : 0;

  const totalCost =
    results?.records.reduce((s, r) => {
      if (!r.costs) return s;
      return s + Object.values(r.costs).reduce((a, v) => a + v, 0);
    }, 0) ?? 0;

  // ─── Render ───────────────────────────────────────────────────────────────

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
            Evaluation
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
            Pipeline evaluation
          </h1>

          {/* Tab navigation */}
          <nav style={{ display: "flex" }}>
            {tabs.map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "15px",
                  fontWeight: 500,
                  color: "#201515",
                  padding: "12px 16px",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  boxShadow:
                    activeTab === id
                      ? "rgb(255, 79, 0) 0px -4px 0px 0px inset"
                      : "none",
                }}
                onMouseEnter={(e) => {
                  if (activeTab !== id)
                    (e.currentTarget as HTMLButtonElement).style.boxShadow =
                      "rgb(197, 192, 177) 0px -4px 0px 0px inset";
                }}
                onMouseLeave={(e) => {
                  if (activeTab !== id)
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = "none";
                }}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </section>

      {/* ── Free Claim tab ────────────────────────────────────────────────── */}
      {activeTab === "free-claim" && (
        <section
          style={{ maxWidth: "1200px", margin: "0 auto", padding: "48px 24px" }}
        >
          <div className="eval-grid">
            {/* Form */}
            <div
              style={{
                border: "1px solid #c5c0b1",
                borderRadius: "8px",
                padding: "40px",
                backgroundColor: "#fffefb",
              }}
            >
              <h2
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "24px",
                  fontWeight: 600,
                  color: "#201515",
                  letterSpacing: "-0.48px",
                  marginBottom: "6px",
                }}
              >
                Submit a claim
              </h2>
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "15px",
                  color: "#939084",
                  marginBottom: "32px",
                }}
              >
                Inject any claim text directly into the pipeline. <br/>
                <b>URL scraping
                is skipped and the claim enters at the query-generation stage.</b>
              </p>

              <form onSubmit={handleClaimSubmit}>
                <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                  {/* Claim text */}
                  <div>
                    <label style={fieldLabel}>Claim text</label>
                    <textarea
                      value={claimText}
                      onChange={(e) => setClaimText(e.target.value)}
                      required
                      rows={5}
                      placeholder="Enter the claim to be fact-checked…"
                      style={{
                        ...inputBase,
                        resize: "vertical",
                        lineHeight: 1.5,
                      }}
                      onFocus={(e) => { e.currentTarget.style.borderColor = "#ff4f00"; }}
                      onBlur={(e) => { e.currentTarget.style.borderColor = "#c5c0b1"; }}
                    />
                  </div>

                  {/* Truth label (optional) */}
                  <div>
                    <label style={fieldLabel}>
                      Ground-truth label{" "}
                      <span style={{ fontWeight: 400, color: "#939084", fontSize: "13px" }}>
                        (optional — enables accuracy tracking in Results)
                      </span>
                    </label>
                    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                      {(["", ...TRUTH_LABELS] as TruthLabel[]).map((lbl) => (
                        <button
                          key={lbl}
                          type="button"
                          onClick={() => setTruthLabel(lbl)}
                          style={{
                            padding: "8px 16px",
                            fontFamily: "Inter, sans-serif",
                            fontSize: "14px",
                            fontWeight: 600,
                            color: truthLabel === lbl ? "#fffefb" : "#36342e",
                            backgroundColor:
                              truthLabel === lbl ? "#201515" : "#eceae3",
                            border: `1px solid ${truthLabel === lbl ? "#201515" : "#c5c0b1"}`,
                            borderRadius: "4px",
                            cursor: "pointer",
                            textTransform: lbl ? "capitalize" : "none",
                          }}
                        >
                          {lbl || "None"}
                        </button>
                      ))}
                    </div>
                  </div>

                  <button
                    type="submit"
                    disabled={submittingClaim || !claimText.trim()}
                    style={{
                      padding: "12px 24px",
                      fontFamily: "Inter, sans-serif",
                      fontSize: "15px",
                      fontWeight: 600,
                      color: "#fffefb",
                      backgroundColor:
                        submittingClaim || !claimText.trim() ? "#b5b2aa" : "#ff4f00",
                      border: "none",
                      borderRadius: "4px",
                      cursor:
                        submittingClaim || !claimText.trim() ? "not-allowed" : "pointer",
                      alignSelf: "flex-start",
                    }}
                  >
                    {submittingClaim ? "Submitting…" : "Submit claim"}
                  </button>
                </div>
              </form>

              {claimResult && (
                <div
                  style={{
                    marginTop: "24px",
                    padding: "20px",
                    border: "1px solid #c5c0b1",
                    borderRadius: "8px",
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
                      marginBottom: "10px",
                    }}
                  >
                    Claim accepted
                  </p>
                  <p
                    style={{
                      fontFamily: "Inter, sans-serif",
                      fontSize: "14px",
                      color: "#36342e",
                      marginBottom: "6px",
                    }}
                  >
                    <span style={{ fontWeight: 600, color: "#201515" }}>Post ID: </span>
                    <code
                      style={{
                        fontFamily: "monospace",
                        fontSize: "13px",
                        backgroundColor: "#fffefb",
                        padding: "2px 6px",
                        borderRadius: "3px",
                      }}
                    >
                      {claimResult.post_id}
                    </code>
                  </p>
                  <p
                    style={{
                      fontFamily: "Inter, sans-serif",
                      fontSize: "14px",
                      color: "#ff4f00",
                      fontWeight: 500,
                      margin: 0,
                    }}
                  >
                    {claimResult.message}
                    {!truthLabel &&
                      " Verdict will appear in the Results tab when complete."}
                  </p>
                </div>
              )}

              {claimError && (
                <div
                  style={{
                    marginTop: "24px",
                    padding: "14px 20px",
                    border: "1px solid #c5c0b1",
                    borderRadius: "8px",
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
                    <span style={{ fontWeight: 600, color: "#201515" }}>Error: </span>
                    {claimError}
                  </p>
                </div>
              )}
            </div>

            {/* Side info */}
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <div
                style={{
                  border: "1px solid #c5c0b1",
                  borderRadius: "8px",
                  padding: "24px",
                  backgroundColor: "#fffefb",
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
                    marginBottom: "12px",
                  }}
                >
                  How it works
                </p>
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "14px",
                    color: "#36342e",
                    lineHeight: 1.6,
                    margin: 0,
                  }}
                >
                  Submitted claims skip URL scraping and enter the pipeline at
                  the <strong>query generation</strong> stage. If you provide a
                  ground-truth label, the system verdict is compared against it
                  and accuracy is tracked in the Results tab.
                </p>
              </div>

              <div
                style={{
                  border: "1px solid #c5c0b1",
                  borderRadius: "8px",
                  padding: "24px",
                  backgroundColor: "#fffefb",
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
                    marginBottom: "12px",
                  }}
                >
                  Label mapping
                </p>
                {[
                  { input: "supported", output: "VERIFIED" },
                  { input: "refuted", output: "REFUTED" },
                  { input: "NEI", output: "NEI" },
                ].map(({ input, output }) => (
                  <div
                    key={input}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "6px 0",
                      borderBottom: "1px solid #eceae3",
                    }}
                  >
                    <span
                      style={{
                        fontFamily: "Inter, sans-serif",
                        fontSize: "13px",
                        color: "#36342e",
                      }}
                    >
                      {input}
                    </span>
                    <span
                      style={{
                        fontFamily: "Inter, sans-serif",
                        fontSize: "12px",
                        fontWeight: 600,
                        color: output === "VERIFIED" ? "#ff4f00" : "#36342e",
                        textTransform: "uppercase",
                        letterSpacing: "0.5px",
                      }}
                    >
                      {output}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* ── MOCHEG Batch tab ──────────────────────────────────────────────── */}
      {activeTab === "mocheg-batch" && (
        <section
          style={{ maxWidth: "1200px", margin: "0 auto", padding: "48px 24px" }}
        >
          {/* If batch is running/done, show progress panel */}
          {batchResponse ? (
            <BatchProgress
              postIds={batchResponse.post_ids}
              total={batchResponse.submitted}
              onReset={handleBatchReset}
            />
          ) : (
            <div className="eval-grid">
              {/* Config card */}
              <div
                style={{
                  border: "1px solid #c5c0b1",
                  borderRadius: "8px",
                  padding: "40px",
                  backgroundColor: "#fffefb",
                }}
              >
                <h2
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "24px",
                    fontWeight: 600,
                    color: "#201515",
                    letterSpacing: "-0.48px",
                    marginBottom: "6px",
                  }}
                >
                  MOCHEG batch run
                </h2>
                <p
                  style={{
                    fontFamily: "Inter, sans-serif",
                    fontSize: "15px",
                    color: "#939084",
                    marginBottom: "32px",
                  }}
                >
                  Randomly samples claims from the MOCHEG test set and submits
                  them to the pipeline. Ground-truth labels are loaded
                  automatically — accuracy is tracked in real time.
                </p>

                <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                  {/* Sample size */}
                  <div>
                    <label style={fieldLabel}>
                      Sample size{" "}
                      <span style={{ fontWeight: 400, color: "#939084", fontSize: "13px" }}>
                        (1 – 100)
                      </span>
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={batchSize}
                      onChange={(e) =>
                        setBatchSize(Math.max(1, Math.min(100, Number(e.target.value))))
                      }
                      style={{ ...inputBase, width: "160px" }}
                      onFocus={(e) => { e.currentTarget.style.borderColor = "#ff4f00"; }}
                      onBlur={(e) => { e.currentTarget.style.borderColor = "#c5c0b1"; }}
                    />
                  </div>

                  {/* Seed */}
                  <div>
                    <label style={fieldLabel}>
                      Random seed{" "}
                      <span style={{ fontWeight: 400, color: "#939084", fontSize: "13px" }}>
                        (controls which claims are sampled)
                      </span>
                    </label>
                    <input
                      type="number"
                      value={batchSeed}
                      onChange={(e) => setBatchSeed(Number(e.target.value))}
                      style={{ ...inputBase, width: "160px" }}
                      onFocus={(e) => { e.currentTarget.style.borderColor = "#ff4f00"; }}
                      onBlur={(e) => { e.currentTarget.style.borderColor = "#c5c0b1"; }}
                    />
                  </div>

                  <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
                    <button
                      onClick={handlePreview}
                      disabled={loadingPreview}
                      style={{
                        padding: "10px 20px",
                        fontFamily: "Inter, sans-serif",
                        fontSize: "15px",
                        fontWeight: 600,
                        color: "#36342e",
                        backgroundColor: "#eceae3",
                        border: "1px solid #c5c0b1",
                        borderRadius: "4px",
                        cursor: loadingPreview ? "not-allowed" : "pointer",
                      }}
                    >
                      {loadingPreview ? "Loading…" : "Preview sample"}
                    </button>

                    <button
                      onClick={handleBatchRun}
                      disabled={batchRunning}
                      style={{
                        padding: "10px 24px",
                        fontFamily: "Inter, sans-serif",
                        fontSize: "15px",
                        fontWeight: 600,
                        color: "#fffefb",
                        backgroundColor: batchRunning ? "#b5b2aa" : "#ff4f00",
                        border: "none",
                        borderRadius: "4px",
                        cursor: batchRunning ? "not-allowed" : "pointer",
                      }}
                    >
                      {batchRunning ? "Submitting…" : `Run ${batchSize} claims`}
                    </button>
                  </div>
                </div>

                {batchError && (
                  <div
                    style={{
                      marginTop: "24px",
                      padding: "14px 20px",
                      border: "1px solid #c5c0b1",
                      borderRadius: "8px",
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
                      <span style={{ fontWeight: 600, color: "#201515" }}>Error: </span>
                      {batchError}
                    </p>
                  </div>
                )}

                {/* Preview list */}
                {previewError && (
                  <p
                    style={{
                      marginTop: "16px",
                      fontFamily: "Inter, sans-serif",
                      fontSize: "14px",
                      color: "#36342e",
                    }}
                  >
                    <span style={{ fontWeight: 600 }}>Preview error: </span>
                    {previewError}
                  </p>
                )}

                {preview && (
                  <div style={{ marginTop: "32px" }}>
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
                      Sample preview — {preview.length} claims
                    </p>
                    <div
                      style={{
                        border: "1px solid #c5c0b1",
                        borderRadius: "8px",
                        overflow: "hidden",
                        maxHeight: "360px",
                        overflowY: "auto",
                      }}
                    >
                      {preview.map((claim, i) => (
                        <div
                          key={claim.claim_id}
                          style={{
                            padding: "14px 20px",
                            borderBottom:
                              i < preview.length - 1 ? "1px solid #eceae3" : "none",
                            backgroundColor: i % 2 === 0 ? "#fffefb" : "#fffdf9",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "flex-start",
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
                                lineHeight: 1.5,
                                flex: 1,
                              }}
                            >
                              <span
                                style={{
                                  fontWeight: 600,
                                  color: "#939084",
                                  fontSize: "12px",
                                  marginRight: "8px",
                                }}
                              >
                                #{claim.claim_id}
                              </span>
                              {claim.claim_text}
                            </p>
                            <span
                              style={{
                                fontFamily: "Inter, sans-serif",
                                fontSize: "11px",
                                fontWeight: 600,
                                color:
                                  claim.truth_label === "supported"
                                    ? "#ff4f00"
                                    : "#939084",
                                textTransform: "uppercase",
                                letterSpacing: "0.5px",
                                whiteSpace: "nowrap",
                                flexShrink: 0,
                              }}
                            >
                              {claim.truth_label}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Side info */}
              <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                <div
                  style={{
                    border: "1px solid #c5c0b1",
                    borderRadius: "8px",
                    padding: "24px",
                    backgroundColor: "#fffefb",
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
                      marginBottom: "12px",
                    }}
                  >
                    About MOCHEG
                  </p>
                  <p
                    style={{
                      fontFamily: "Inter, sans-serif",
                      fontSize: "14px",
                      color: "#36342e",
                      lineHeight: 1.6,
                      margin: "0 0 12px",
                    }}
                  >
                    MOCHEG is a multi-modal claim verification benchmark with
                    ground-truth labels (<em>supported</em>, <em>refuted</em>,{" "}
                    <em>NEI</em>) sourced from Snopes.
                  </p>
                  <p
                    style={{
                      fontFamily: "Inter, sans-serif",
                      fontSize: "14px",
                      color: "#36342e",
                      lineHeight: 1.6,
                      margin: 0,
                    }}
                  >
                    Claims are loaded from{" "}
                    <code
                      style={{
                        fontFamily: "monospace",
                        fontSize: "12px",
                        backgroundColor: "#eceae3",
                        padding: "2px 5px",
                        borderRadius: "3px",
                      }}
                    >
                      mocheg/test/Corpus2.csv
                    </code>{" "}
                    on the backend server. Changing the seed samples a different
                    subset of claims.
                  </p>
                </div>

                <div
                  style={{
                    border: "1px solid #c5c0b1",
                    borderRadius: "8px",
                    padding: "24px",
                    backgroundColor: "#fffefb",
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
                      marginBottom: "12px",
                    }}
                  >
                    Pipeline stages
                  </p>
                  {[
                    "Skips URL scraping",
                    "Enters at Query Generation",
                    "Evidence Retrieval",
                    "Media Verification",
                    "Post Judge → verdict",
                  ].map((step, i) => (
                    <div
                      key={step}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        padding: "6px 0",
                        borderBottom: i < 4 ? "1px solid #eceae3" : "none",
                      }}
                    >
                      <span
                        style={{
                          fontFamily: "Inter, sans-serif",
                          fontSize: "11px",
                          fontWeight: 600,
                          color: i === 0 ? "#939084" : "#ff4f00",
                          textTransform: "uppercase",
                          letterSpacing: "0.5px",
                          width: "24px",
                          flexShrink: 0,
                        }}
                      >
                        {i === 0 ? "—" : `0${i}`}
                      </span>
                      <span
                        style={{
                          fontFamily: "Inter, sans-serif",
                          fontSize: "13px",
                          color: i === 0 ? "#939084" : "#36342e",
                        }}
                      >
                        {step}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── Results tab ───────────────────────────────────────────────────── */}
      {activeTab === "results" && (
        <section
          style={{ maxWidth: "1200px", margin: "0 auto", padding: "48px 24px" }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "32px",
              flexWrap: "wrap",
              gap: "12px",
            }}
          >
            <h2
              style={{
                fontFamily: "Inter, sans-serif",
                fontSize: "24px",
                fontWeight: 600,
                color: "#201515",
                letterSpacing: "-0.48px",
                margin: 0,
              }}
            >
              All evaluation results
            </h2>
            <button
              onClick={fetchResults}
              disabled={loadingResults}
              style={{
                padding: "8px 16px",
                fontFamily: "Inter, sans-serif",
                fontSize: "14px",
                fontWeight: 600,
                color: "#36342e",
                backgroundColor: "#eceae3",
                border: "1px solid #c5c0b1",
                borderRadius: "4px",
                cursor: loadingResults ? "not-allowed" : "pointer",
              }}
            >
              {loadingResults ? "Loading…" : "Refresh"}
            </button>
          </div>

          {resultsError && (
            <div
              style={{
                padding: "14px 20px",
                border: "1px solid #c5c0b1",
                borderRadius: "8px",
                marginBottom: "24px",
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
                <span style={{ fontWeight: 600, color: "#201515" }}>Error: </span>
                {resultsError}
              </p>
            </div>
          )}

          {results && (
            <>
              {/* Summary stats */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                  gap: "1px",
                  border: "1px solid #c5c0b1",
                  borderRadius: "8px",
                  overflow: "hidden",
                  backgroundColor: "#c5c0b1",
                  marginBottom: "32px",
                }}
              >
                <StatCell label="Submitted" value={results.total_submitted} sub="total claims" />
                <StatCell label="Completed" value={results.completed} sub="verdicts in" />
                <StatCell label="Correct" value={results.correct} sub="accurate verdicts" />
                <StatCell
                  label="Accuracy"
                  value={`${(results.accuracy * 100).toFixed(1)}%`}
                  sub="overall"
                />
                <StatCell
                  label="Avg Latency"
                  value={`${avgLatency.toFixed(1)}s`}
                  sub="per claim"
                />
                <StatCell
                  label="Total Cost"
                  value={`$${totalCost.toFixed(4)}`}
                  sub="pipeline"
                />
              </div>

              {/* Per-label accuracy */}
              {Object.keys(results.per_label).length > 0 && (
                <div
                  style={{
                    border: "1px solid #c5c0b1",
                    borderRadius: "8px",
                    padding: "32px",
                    backgroundColor: "#fffefb",
                    marginBottom: "32px",
                  }}
                >
                  <h3
                    style={{
                      fontFamily: "Inter, sans-serif",
                      fontSize: "18px",
                      fontWeight: 600,
                      color: "#201515",
                      marginBottom: "24px",
                    }}
                  >
                    Accuracy by label
                  </h3>
                  {Object.entries(results.per_label).map(([label, { correct, total }]) => (
                    <AccuracyBar
                      key={label}
                      label={label}
                      correct={correct}
                      total={total}
                    />
                  ))}
                </div>
              )}

              {/* Records table */}
              {results.records.length > 0 ? (
                <div
                  style={{
                    border: "1px solid #c5c0b1",
                    borderRadius: "8px",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      padding: "16px 24px",
                      borderBottom: "1px solid #c5c0b1",
                      backgroundColor: "#eceae3",
                    }}
                  >
                    <h3
                      style={{
                        fontFamily: "Inter, sans-serif",
                        fontSize: "15px",
                        fontWeight: 600,
                        color: "#201515",
                        margin: 0,
                      }}
                    >
                      All records ({results.records.length})
                    </h3>
                  </div>
                  <div style={{ overflowX: "auto" }}>
                    <table
                      style={{
                        width: "100%",
                        borderCollapse: "collapse",
                        fontFamily: "Inter, sans-serif",
                        fontSize: "14px",
                      }}
                    >
                      <thead>
                        <tr style={{ backgroundColor: "#fffefb" }}>
                          {["Claim ID", "Claim", "Truth", "Verdict", "Correct", "Latency", "Cost"].map(
                            (col) => (
                              <th
                                key={col}
                                style={{
                                  padding: "10px 16px",
                                  textAlign: "left",
                                  fontWeight: 600,
                                  color: "#939084",
                                  fontSize: "12px",
                                  textTransform: "uppercase",
                                  letterSpacing: "0.5px",
                                  borderBottom: "1px solid #c5c0b1",
                                  whiteSpace: "nowrap",
                                }}
                              >
                                {col}
                              </th>
                            )
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {results.records.map((record, idx) => (
                          <tr
                            key={record.post_id}
                            style={{
                              backgroundColor: idx % 2 === 0 ? "#fffefb" : "#fffdf9",
                              borderBottom: "1px solid #eceae3",
                            }}
                          >
                            <td
                              style={{
                                padding: "10px 16px",
                                color: "#36342e",
                                fontWeight: 500,
                                whiteSpace: "nowrap",
                              }}
                            >
                              {record.dataset_claim_id}
                            </td>
                            <td
                              style={{
                                padding: "10px 16px",
                                color: "#36342e",
                                maxWidth: "280px",
                              }}
                            >
                              <span
                                style={{
                                  display: "-webkit-box",
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: "vertical",
                                  overflow: "hidden",
                                }}
                                title={record.claim_text}
                              >
                                {record.claim_text}
                              </span>
                            </td>
                            <td
                              style={{
                                padding: "10px 16px",
                                color: "#36342e",
                                whiteSpace: "nowrap",
                                textTransform: "capitalize",
                              }}
                            >
                              {record.truth_label || "—"}
                            </td>
                            <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                              <VerdictBadge verdict={record.system_verdict} />
                            </td>
                            <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                              {record.correct === null ? (
                                <span style={{ color: "#939084" }}>—</span>
                              ) : record.correct ? (
                                <span style={{ color: "#ff4f00", fontWeight: 600 }}>✓</span>
                              ) : (
                                <span style={{ color: "#36342e", fontWeight: 600 }}>✗</span>
                              )}
                            </td>
                            <td
                              style={{
                                padding: "10px 16px",
                                color: "#36342e",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {record.latency_seconds != null
                                ? `${record.latency_seconds.toFixed(1)}s`
                                : "—"}
                            </td>
                            <td
                              style={{
                                padding: "10px 16px",
                                color: "#36342e",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {record.costs && Object.keys(record.costs).length > 0 ? (
                                <span title={Object.entries(record.costs).map(([k, v]) => `${k}: $${v.toFixed(4)}`).join("\n")}>
                                  ${Object.values(record.costs).reduce((a, v) => a + v, 0).toFixed(4)}
                                </span>
                              ) : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div
                  style={{
                    border: "1px solid #c5c0b1",
                    borderRadius: "8px",
                    padding: "48px",
                    textAlign: "center",
                    backgroundColor: "#fffefb",
                  }}
                >
                  <p
                    style={{
                      fontFamily: "Inter, sans-serif",
                      fontSize: "16px",
                      color: "#939084",
                      margin: 0,
                    }}
                  >
                    No claims with ground-truth labels submitted yet.
                  </p>
                </div>
              )}
            </>
          )}

          {!results && !loadingResults && !resultsError && (
            <div
              style={{
                border: "1px solid #c5c0b1",
                borderRadius: "8px",
                padding: "48px",
                textAlign: "center",
                backgroundColor: "#fffefb",
              }}
            >
              <p
                style={{
                  fontFamily: "Inter, sans-serif",
                  fontSize: "16px",
                  color: "#939084",
                  margin: 0,
                }}
              >
                Click Refresh to load evaluation results.
              </p>
            </div>
          )}
        </section>
      )}

      <style jsx>{`
        .eval-grid {
          display: grid;
          grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
          gap: 40px;
          align-items: start;
        }
        @media (max-width: 768px) {
          .eval-grid {
            grid-template-columns: 1fr;
            gap: 24px;
          }
        }
      `}</style>
    </div>
  );
}
