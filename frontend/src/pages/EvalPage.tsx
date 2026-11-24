import { useEffect, useState } from "react";
import { api, type LabelValue, type Metrics, type PolicyRow, type ReviewSummary } from "../lib/api";
import { Eyebrow, SectionChip, Stamp } from "../components/ui";
import { fmtMs, fmtUsd } from "../lib/format";
import { errorText, useLatest } from "../lib/latest";

// One series, one colour: the section's own chip carries its identity.
const SECTION_BAR = "#2563b8";
const ROWS: LabelValue[] = ["VIOLATING", "NEEDS_REVIEW", "ALLOWED"];

export function EvalPage({ initial, openQueue }: { initial?: string; openQueue: (version: string) => void }) {
  const [versions, setVersions] = useState<PolicyRow[]>([]);
  const [version, setVersion] = useState<string | undefined>();
  const [m, setM] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Analyst checks count on every posting, not only the fixed set: that is where analysts work.
  const [checks, setChecks] = useState<ReviewSummary | null>(null);

  useEffect(() => {
    api.policies().then((rows) => {
      setVersions(rows);
      const wanted = initial && rows.some((r) => r.version === initial) ? initial : undefined;
      setVersion(wanted ?? (rows.find((r) => r.status === "published") ?? rows[0])?.version);
    });
  }, [initial]);

  const latest = useLatest();
  useEffect(() => {
    if (!version) return;
    setM(null);
    setError(null);
    latest.run(api.metrics(version), setM, (e) => setError(errorText(e)));
    setChecks(null);
    api
      .metrics(version, false)
      .then((all) => setChecks(all.reviews))
      .catch(() => setChecks(null));
  }, [version, latest]);

  return (
    <div className="report">
      <div className="report-head">
        <div>
          <Eyebrow>Fixed evaluation set · 400 held-out postings</Eyebrow>
          <h2 className="h-serif" style={{ fontSize: 28 }}>How the policy is applied</h2>
        </div>
        <div className="btn-row">
          <label className="small muted" htmlFor="ver">Policy</label>
          <select id="ver" value={version} onChange={(e) => setVersion(e.target.value)} className="btn">
            {versions.map((v) => (
              <option key={v.version} value={v.version}>{v.version} · {v.status}</option>
            ))}
          </select>
          {version && <button className="btn" onClick={() => openQueue(version)}>Browse these decisions →</button>}
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {m && m.n === 0 && (
        <div className="note-box">
          No eval-set labels under {version} yet. Run <code>make eval</code>, or shadow-run this version from the Policy page.
        </div>
      )}

      {m && m.n > 0 && (
        <>
          <div className="note-box">
            Every decision is checked against the policy's own rules: a <strong>VIOLATING</strong> label needs a policy
            section backed by a quote found verbatim in the posting; <strong>NEEDS_REVIEW</strong> comes from a review-only
            section (or a failure a human must see); <strong>ALLOWED</strong> means no written rule applies.
          </div>

          <div className="tiles">
            <Tile
              label="Blocks grounded"
              value={m.blocks.total ? `${Math.round((m.blocks.with_verified_quote / m.blocks.total) * 100)}%` : "—"}
              sub={`${m.blocks.with_verified_quote} of ${m.blocks.total} VIOLATING decisions cite a section with a verified quote`}
            />
            <Tile
              label="Reviews by policy"
              value={m.labels.NEEDS_REVIEW ? `${Math.round((m.review_routes.section / m.labels.NEEDS_REVIEW) * 100)}%` : "—"}
              sub={`${m.review_routes.section} of ${m.labels.NEEDS_REVIEW} routed by a policy section${m.review_routes.failed ? ` · ${m.review_routes.failed} failures` : ""}`}
            />
            <Tile label="Review rate" value={`${Math.round(m.review_share * 100)}%`} sub="share sent to an analyst" />
            <Tile
              label="Cost / 1,000"
              value={fmtUsd(m.cost_per_1k_usd)}
              sub={
                // cost_unpriced: decisions by a model with no list price (OpenAI, a compatible endpoint), counted as $0
                (m as { cost_unpriced?: number }).cost_unpriced
                  ? `at least: ${(m as { cost_unpriced?: number }).cost_unpriced} postings used an unpriced model ($0)`
                  : `${fmtUsd(m.total_cost_usd)} for ${m.n} postings`
              }
            />
            <Tile label="Latency p50 / p95" value={`${fmtMs(m.latency_ms.p50)}`} sub={`p95 ${fmtMs(m.latency_ms.p95)} · max ${fmtMs(m.latency_ms.max)}`} />
            <Tile label="Escalated" value={`${Math.round(m.escalation_rate * 100)}%`} sub={Object.entries(m.tiers).map(([k, v]) => `${k} ${v}`).join(" · ")} />
          </div>

          <div className="two">
            <div className="card">
              <h4 className="eyebrow">Decisions · label and the sections behind it</h4>
              <table className="prf">
                <thead>
                  <tr><th>Label</th><th>Postings</th><th>Share</th></tr>
                </thead>
                <tbody>
                  {ROWS.map((r) => (
                    <tr key={r}>
                      <td><Stamp label={r} /></td>
                      <td className="mono">{m.labels[r] ?? 0}</td>
                      <td className="mono">{m.n ? `${Math.round(((m.labels[r] ?? 0) / m.n) * 100)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h4 className="eyebrow">Section combinations cited</h4>
              <table className="prf">
                <thead>
                  <tr><th>Sections</th><th>Postings</th></tr>
                </thead>
                <tbody>
                  {Object.keys(m.section_combos).length === 0 && (
                    <tr><td colSpan={2} className="muted small">No section matched in this run.</td></tr>
                  )}
                  {Object.entries(m.section_combos).slice(0, 8).map(([combo, n]) => (
                    <tr key={combo}>
                      <td>{combo.split(" + ").map((sid) => <SectionChip key={sid} id={sid} />)}</td>
                      <td className="mono">{n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {checks && <AnalystChecks s={checks} />}

          <div className="card">
            <h4 className="eyebrow">Which sections fire</h4>
            <div className="bars" style={{ marginTop: 10 }}>
              {Object.keys(m.section_counts).length === 0 && <span className="muted small">No section matched in this run.</span>}
              {Object.entries(m.section_counts).map(([sid, n]) => {
                const maxN = Math.max(...Object.values(m.section_counts));
                return (
                  <div className="bar-row" key={sid}>
                    <SectionChip id={sid} withName={false} />
                    <div className="bar-track" style={{ width: `${(n / maxN) * 100}%` }}>
                      <i style={{ flex: 1, background: SECTION_BAR, borderRadius: 2 }} title={`${n} postings cite ${sid}`} />
                    </div>
                    <span className="mono small">{n}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {m.n_scored > 0 && (
            <div className="card">
              <h4 className="eyebrow">Against the dataset label · secondary</h4>
              <p className="muted small" style={{ margin: "6px 0 10px" }}>
                EMSCAD marks whether a posting was fraud, not whether it breaks this policy, so these scores also count
                frauds no written section covers. <em>Strict</em> counts only VIOLATING as a fraud call; <em>flagged</em>{" "}
                also counts NEEDS_REVIEW. Of {m.n_scored} scored: fraud postings ALLOWED {m.confusion.ALLOWED.fraud}, legitimate
                postings blocked {m.confusion.VIOLATING.legit}.
              </p>
              <table className="prf">
                <thead>
                  <tr><th>Scoring</th><th>Precision</th><th>Recall</th><th>F1</th><th>TP</th><th>FP</th><th>FN</th></tr>
                </thead>
                <tbody>
                  {([["Strict (VIOLATING only)", m.strict], ["Flagged (VIOLATING + REVIEW)", m.flagged]] as const).map(([n, s]) => (
                    <tr key={n}>
                      <td>{n}</td>
                      <td>{s.precision.toFixed(2)}</td>
                      <td>{s.recall.toFixed(2)}</td>
                      <td>{s.f1.toFixed(2)}</td>
                      <td className="mono">{s.tp}</td>
                      <td className="mono">{s.fp}</td>
                      <td className="mono">{s.fn}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="tile">
      <Eyebrow>{label}</Eyebrow>
      <div className="num">{value}</div>
      <div className="sub">{sub}</div>
    </div>
  );
}

/** What analysts said about the agent's decisions under this version: the production quality signal
 * the dataset label cannot give (DESIGN.md §5). Biased by which cases analysts chose to open. */
function AnalystChecks({ s }: { s: ReviewSummary }) {
  return (
    <div className="card">
      <h4 className="eyebrow">Analyst checks · every posting under this version</h4>
      {s.checked === 0 ? (
        <p className="muted small" style={{ margin: 0 }}>
          No decision has been checked yet. Open a case on Decisions and choose <em>Agree</em> or <em>Overturn</em>; the
          agreement rate per label shows up here.
        </p>
      ) : (
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-start" }}>
          <div style={{ minWidth: 200 }}>
            <Tile
              label="Upheld by analysts"
              value={s.agreement_rate === null ? "—" : `${Math.round(s.agreement_rate * 100)}%`}
              sub={`${s.agreed} agreed, ${s.overturned} overturned of ${s.checked} checked`}
            />
          </div>
          <table className="prf" style={{ flex: 1, minWidth: 260 }}>
            <thead>
              <tr><th>Agent said</th><th>Checked</th><th>Overturned</th><th>Upheld</th></tr>
            </thead>
            <tbody>
              {ROWS.filter((r) => s.by_label[r]).map((r) => {
                const c = s.by_label[r]!;
                return (
                  <tr key={r}>
                    <td><Stamp label={r} /></td>
                    <td className="mono">{c.checked}</td>
                    <td className="mono">{c.overturned}</td>
                    <td>{Math.round(((c.checked - c.overturned) / c.checked) * 100)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {Object.keys(s.transitions).length > 0 && (
            <div className="small">
              <Eyebrow>Overturns</Eyebrow>
              {Object.entries(s.transitions).map(([k, n]) => (
                <div key={k} className="mono">{k.replace("->", " → ")} · {n}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
