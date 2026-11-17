"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  Health,
  Network,
  Part,
  PlantHit,
  RunStatus,
  Shortlist,
  ValidationReport,
} from "@/lib/types";

const SOLVENTS = [
  { value: "ethanol", label: "Ethanol 70%" },
  { value: "water", label: "Water / decoction" },
  { value: "hexane", label: "Hexane" },
];

const DEMO = { plant: "Curcuma longa", part: "rhizome", condition: "colitis" };

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function shortName(name: string, max = 42): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

export default function Workbench() {
  const [health, setHealth] = useState<Health | null>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [conditions, setConditions] = useState<
    { name: string; label: string; targets: number }[]
  >([]);

  const [plantQuery, setPlantQuery] = useState(DEMO.plant);
  const [suggestions, setSuggestions] = useState<PlantHit[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [part, setPart] = useState(DEMO.part);
  const [solvent, setSolvent] = useState("ethanol");
  const [condition, setCondition] = useState(DEMO.condition);
  const [top, setTop] = useState(12);

  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [shortlist, setShortlist] = useState<Shortlist | null>(null);
  const [network, setNetwork] = useState<Network | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docking, setDocking] = useState(false);
  const [dockNote, setDockNote] = useState<string | null>(null);
  const [queueBackend, setQueueBackend] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const suggestionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((payload) => {
        if (cancelled) return;
        setHealth(payload);
        setReachable(true);
      })
      .catch(() => !cancelled && setReachable(false));
    api
      .conditions()
      .then((payload) => {
        if (cancelled) return;
        setConditions(payload.conditions);
        if (!payload.conditions.some((c) => c.name === DEMO.condition)) {
          setCondition(payload.conditions[0]?.name ?? DEMO.condition);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const query = plantQuery.trim();
    if (query.length < 3) {
      setSuggestions([]);
      return;
    }
    if (suggestionTimer.current) clearTimeout(suggestionTimer.current);
    suggestionTimer.current = setTimeout(() => {
      api
        .plants(query)
        .then((payload) => setSuggestions(payload.results.slice(0, 6)))
        .catch(() => setSuggestions([]));
    }, 260);
    return () => {
      if (suggestionTimer.current) clearTimeout(suggestionTimer.current);
    };
  }, [plantQuery]);

  async function choosePlant(hit: PlantHit) {
    setPlantQuery(hit.plant);
    setSuggestions([]);
    try {
      const resolved = await api.parts(hit.id);
      setParts(resolved.parts);
      const best = [...resolved.parts].sort((a, b) => b.compounds - a.compounds)[0];
      setPart((current) =>
        resolved.parts.some((item) => item.part === current)
          ? current
          : (best?.part ?? ""),
      );
    } catch (err) {
      setError(message(err));
    }
  }

  const startRun = useCallback(
    async (override?: { plant?: string; part?: string; condition?: string }) => {
      const plant = (override?.plant ?? plantQuery).trim();
      const chosenPart = override?.part ?? part;
      const chosenCondition = override?.condition ?? condition;
      if (!plant || !chosenPart) {
        setError("Choose a plant and a part before running.");
        return;
      }
      setBusy(true);
      setError(null);
      setShortlist(null);
      setNetwork(null);
      setStatus(null);
      setRunId(null);
      setDockNote(null);
      setOpen(new Set());
      try {
        const receipt = await api.createRun({
          plant,
          part: chosenPart,
          solvent,
          condition: chosenCondition,
          top,
        });
        setQueueBackend(receipt.queue);
        setRunId(receipt.run_id);
      } catch (err) {
        setError(message(err));
        setBusy(false);
      }
    },
    [plantQuery, part, solvent, condition, top],
  );

  useEffect(() => {
    if (!runId || shortlist) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const payload = await api.getRun(runId);
        if (cancelled) return;
        setStatus(payload);
        if (payload.status === "complete") {
          const [result, graph] = await Promise.all([
            api.shortlist(runId),
            api.network(runId),
          ]);
          if (cancelled) return;
          setShortlist(result);
          setNetwork(graph);
          setBusy(false);
        } else if (payload.status === "failed") {
          setError(payload.error ?? "The run failed.");
          setBusy(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(message(err));
          setBusy(false);
        }
      }
    };

    void tick();
    const timer = setInterval(tick, 700);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runId, shortlist]);

  async function runLiveDock() {
    if (!runId || !shortlist) return;
    setDocking(true);
    setDockNote(null);
    setError(null);
    try {
      const target =
        shortlist.docking_targets?.[0] ?? Object.keys(shortlist.ranked[0]?.docking ?? {})[0] ?? "PTGS2";
      const result = await api.liveDock(runId, { targets: [target], candidates: 2 });
      setShortlist({
        ...shortlist,
        ranked: result.shortlist,
        docking: result.docking,
        docking_pending: false,
      });
      setDockNote(
        `${result.fresh} fresh Vina run${result.fresh === 1 ? "" : "s"} into ${target}` +
          ` · ${result.reused} cache hit${result.reused === 1 ? "" : "s"} · ${result.vina}`,
      );
    } catch (err) {
      setError(message(err));
    } finally {
      setDocking(false);
    }
  }

  const targets = shortlist
    ? (shortlist.docking_targets ??
      Array.from(new Set(shortlist.ranked.flatMap((row) => Object.keys(row.docking)))))
    : [];
  const stageLabel = status
    ? status.status === "queued"
      ? "Queued"
      : status.stage.charAt(0).toUpperCase() + status.stage.slice(1)
    : "Starting";

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden>
            ✦
          </span>
          <div>
            <h1>PhytoLens</h1>
            <p>Evidence engine for herbal and AYUSH formulations</p>
          </div>
        </div>
        <div className="topbar-right">
          {reachable !== null && (
            <span className={`pill ${reachable ? "pill-ok" : "pill-off"}`}>
              <i />
              {reachable
                ? `engine ${health?.version ?? ""}${health?.queue ? ` · queue ${health.queue.backend}` : ""}` +
                  (health?.queue?.backend === "redis" && health.queue.worker_alive === false
                    ? " · no worker"
                    : "")
                : "engine unreachable"}
            </span>
          )}
          <span className="pill pill-quiet">in-silico · research use only</span>
        </div>
      </header>

      <main className="layout">
        <aside className="panel">
          <div className="panel-head">
            <span className="eyebrow">Formulation</span>
            <h2>What are you testing?</h2>
          </div>

          <div className="field">
            <label htmlFor="plant">Plant</label>
            <div className="suggest-anchor">
              <input
                id="plant"
                value={plantQuery}
                autoComplete="off"
                onChange={(event) => setPlantQuery(event.target.value)}
                placeholder="e.g. Curcuma longa, turmeric"
              />
              {suggestions.length > 0 && (
                <ul className="suggestions">
                  {suggestions.map((hit) => (
                    <li key={`${hit.id}-${hit.matched}`}>
                      <button type="button" onClick={() => choosePlant(hit)}>
                        <strong>{hit.plant}</strong>
                        <span>
                          {hit.common_name ? `${hit.common_name} · ` : ""}
                          matched “{hit.matched}”
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="field">
            <label htmlFor="part">Plant part</label>
            {parts.length > 0 ? (
              <select
                id="part"
                value={part}
                onChange={(event) => setPart(event.target.value)}
              >
                {parts.map((item) => (
                  <option key={item.part} value={item.part}>
                    {item.part.replace(/_/g, " ")} · {item.compounds} compounds
                  </option>
                ))}
              </select>
            ) : (
              <input
                id="part"
                value={part}
                onChange={(event) => setPart(event.target.value)}
                placeholder="rhizome, leaf, root, exudate…"
              />
            )}
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor="solvent">Solvent</label>
              <select
                id="solvent"
                value={solvent}
                onChange={(event) => setSolvent(event.target.value)}
              >
                {SOLVENTS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="condition">Condition</label>
              <select
                id="condition"
                value={condition}
                onChange={(event) => setCondition(event.target.value)}
              >
                {(conditions.length > 0
                  ? conditions
                  : [{ name: DEMO.condition, label: "Colitis", targets: 66 }]
                ).map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.label} · {item.targets} targets
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="field">
            <label htmlFor="top">
              Shortlist size <span className="field-hint">{top}</span>
            </label>
            <input
              id="top"
              type="range"
              min={5}
              max={40}
              step={1}
              value={top}
              onChange={(event) => setTop(Number(event.target.value))}
            />
          </div>

          <button
            type="button"
            className="btn btn-primary btn-block"
            onClick={() => startRun()}
            disabled={busy}
          >
            {busy ? "Running…" : "Rank this formulation"}
          </button>
          <button
            type="button"
            className="btn btn-quiet btn-block"
            onClick={() =>
              startRun({ ...DEMO })
            }
            disabled={busy}
          >
            Load the demo formulation
          </button>

          <div className="panel-note">
            <p>
              Ranking gates on condition-target overlap, then weights docking.
              Docking is the only term that does not reward how much a compound
              has been studied.
            </p>
            {health && (
              <dl>
                <div>
                  <dt>Corpus</dt>
                  <dd>{health.corpus.compounds.toLocaleString()} compounds</dd>
                </div>
                <div>
                  <dt>Plants</dt>
                  <dd>{health.corpus.plants.toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Docking</dt>
                  <dd>{health.vina}</dd>
                </div>
              </dl>
            )}
          </div>
        </aside>

        <section className="results">
          {error && (
            <div className="error" role="alert">
              <strong>Something went wrong.</strong>
              <span>{error}</span>
            </div>
          )}

          {!shortlist && busy && (
            <div className="card running">
              <span className="eyebrow">Run {runId ?? ""}</span>
              <h2>{stageLabel}</h2>
              <div className="progress">
                <i style={{ width: `${Math.round((status?.progress ?? 0.05) * 100)}%` }} />
              </div>
              <p>
                Resolving the plant, applying the solvent window, scoring
                condition overlap and attaching docking scores.
                {queueBackend === "redis" ? " Queued through Redis." : " Queued in-process."}
              </p>
            </div>
          )}

          {!shortlist && !busy && (
            <div className="card empty">
              <span className="eyebrow">Research shortlist</span>
              <h2>Which compound should your lab test first?</h2>
              <p>
                Pick a plant, the part the preparation actually uses, and the
                solvent. PhytoLens returns a ranked, explainable shortlist with
                docking scores, the evidence behind every compound–target link,
                and a PDF that carries its own caveats.
              </p>
              <div className="empty-grid">
                <div>
                  <span>01</span>
                  <p>168 compounds in a turmeric rhizome, narrowed by solvent and target overlap.</p>
                </div>
                <div>
                  <span>02</span>
                  <p>Annotation ranking returns the same six volatiles for a quarter of the corpus. We show it, then correct it.</p>
                </div>
                <div>
                  <span>03</span>
                  <p>Docking re-orders the shortlist, and every score keeps its PDB, box and engine version.</p>
                </div>
              </div>
            </div>
          )}

          {shortlist && (
            <>
              <div className="result-head">
                <div>
                  <span className="eyebrow">
                    Shortlist · {shortlist.ranked.length} of{" "}
                    {shortlist.funnel.with_condition_target} candidates
                  </span>
                  <h2 className="plant-title">{shortlist.formulation.plant}</h2>
                  <p className="meta">
                    {shortlist.formulation.part.replace(/_/g, " ")} ·{" "}
                    {shortlist.formulation.solvent_label} →{" "}
                    <strong>{shortlist.condition.name}</strong> ·{" "}
                    {shortlist.condition.targets} condition targets ·{" "}
                    {shortlist.condition.source}
                  </p>
                </div>
                <div className="result-actions">
                  {runId && (
                    <a
                      className="btn btn-ghost"
                      href={api.reportUrl(runId)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      PDF report
                    </a>
                  )}
                  {runId && (
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={runLiveDock}
                      disabled={docking}
                    >
                      {docking ? "Docking…" : "Live-dock top 2"}
                    </button>
                  )}
                </div>
              </div>

              <div className="stats">
                <Stat label="In this part" value={shortlist.funnel.in_part} />
                <Stat label="Pass extraction" value={shortlist.funnel.pass_extraction} />
                <Stat
                  label="Reach a target"
                  value={shortlist.funnel.with_condition_target}
                />
                <Stat
                  label="Docked"
                  value={`${shortlist.docking.docked}/${shortlist.docking.candidates}`}
                  tone={shortlist.docking.partial ? "warn" : undefined}
                />
              </div>

              {dockNote && <div className="notice notice-live">{dockNote}</div>}

              {shortlist.docking_pending ? (
                <div className="notice notice-warn">
                  Docking has not run for this formulation. The docking weight was
                  redistributed, so this ordering is preliminary and must not be
                  presented as final.
                </div>
              ) : shortlist.docking.partial ? (
                <div className="notice notice-warn">
                  Partial docking coverage: {shortlist.docking.docked} of{" "}
                  {shortlist.docking.candidates} candidates carry a Vina score.
                  Undocked rows are not directly comparable with docked ones.
                </div>
              ) : (
                <div className="notice">
                  All candidates docked against {targets.length} target
                  {targets.length === 1 ? "" : "s"} · {shortlist.formulation.solvent_label} ·
                  config {shortlist.config_hashes.ranking}
                </div>
              )}

              <div className="table-wrap">
                <table className="shortlist">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Compound</th>
                      <th className="right">Score</th>
                      <th className="right">Targets</th>
                      <th className="right">Measured</th>
                      {targets.map((target) => (
                        <th key={target} className="right">
                          {target}
                        </th>
                      ))}
                      <th>Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shortlist.ranked.map((row) => {
                      const expanded = open.has(row.id);
                      return (
                        <Fragment key={row.id}>
                          <tr className={expanded ? "row open" : "row"}>
                            <td className="num">{row.rank}</td>
                            <td>
                              <button
                                type="button"
                                className="compound"
                                onClick={() =>
                                  setOpen((current) => {
                                    const next = new Set(current);
                                    if (next.has(row.id)) next.delete(row.id);
                                    else next.add(row.id);
                                    return next;
                                  })
                                }
                                aria-expanded={expanded}
                              >
                                {shortName(row.name)}
                              </button>
                            </td>
                            <td className="right num">{row.score.toFixed(3)}</td>
                            <td className="right num">{row.overlap.count}</td>
                            <td className="right num">{row.overlap.measured}</td>
                            {targets.map((target) => (
                              <td key={target} className="right num affinity">
                                {row.docking[target] != null
                                  ? row.docking[target].toFixed(2)
                                  : "—"}
                              </td>
                            ))}
                            <td className="flags">
                              {row.flags.length > 0 ? row.flags.join(", ") : "—"}
                            </td>
                          </tr>
                          {expanded && (
                            <tr className="detail">
                              <td colSpan={6 + targets.length}>
                                <div className="detail-grid">
                                  <div>
                                    <h4>Condition targets reached</h4>
                                    <p className="chips">
                                      {row.overlap.genes.map((gene) => (
                                        <span
                                          key={gene.symbol}
                                          className={
                                            gene.measured ? "chip chip-measured" : "chip"
                                          }
                                          title={
                                            gene.measured
                                              ? "Measured link (ChEMBL/BindingDB)"
                                              : "Predicted link (NPASS only)"
                                          }
                                        >
                                          {gene.symbol}
                                        </span>
                                      ))}
                                    </p>
                                    <p className="fineprint">
                                      Filled chips are measured links; outlined chips
                                      are predicted. {row.targets.measured} of{" "}
                                      {row.targets.annotated} annotated targets are
                                      measured overall.
                                    </p>
                                  </div>
                                  <div>
                                    <h4>Score terms</h4>
                                    <div className="terms">
                                      {Object.entries(row.terms).map(([term, value]) => (
                                        <div className="term" key={term}>
                                          <span>{term}</span>
                                          <div className="bar">
                                            <i
                                              style={{
                                                width: `${Math.max(2, Math.round(value * 100))}%`,
                                              }}
                                            />
                                          </div>
                                          <span className="num">{value.toFixed(2)}</span>
                                        </div>
                                      ))}
                                    </div>
                                    <p className="fineprint">
                                      MW {row.mw ?? "—"} · logP{" "}
                                      {row.logp != null ? row.logp.toFixed(2) : "—"} ·
                                      every term is weighted in the config, not in code.
                                    </p>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="foot-grid">
                <div className="card caveats">
                  <h3>Read this with the numbers</h3>
                  <ul>
                    <li>Docking ranks hypotheses. It does not show binding in practice, absorption, safety, or effect in people.</li>
                    <li>Only the panel targets were docked. A compound binding none of them may still act elsewhere.</li>
                    <li>Target annotations are database links: measured (ChEMBL/BindingDB) or predicted (NPASS).</li>
                    <li>Cholesterol and other sterols are left in the table and disclosed rather than quietly filtered.</li>
                  </ul>
                </div>
                <div className="card hubs">
                  <h3>Hub targets</h3>
                  <p className="fineprint">
                    Highest-degree targets in the compound–target–condition graph.
                  </p>
                  <ul>
                    {(network?.hubs ?? []).slice(0, 6).map((hub) => (
                      <li key={hub.id}>
                        <span className="mono">{hub.label}</span>
                        <span className="num">{hub.degree} edges</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </>
          )}
        </section>
      </main>

      <ValidationSection />

      <footer className="footer">
        <span>
          PhytoLens — in-silico prioritisation. Hypotheses for laboratory
          validation only. Not a medical device, not for clinical decisions.
        </span>
        <span>
          IMPPAT 2.0 corpus (CC BY-NC-ND) · Open Targets CC0 · RCSB PDB ·{" "}
          {health?.vina ?? "AutoDock Vina"}
        </span>
      </footer>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "warn";
}) {
  return (
    <div className={`stat ${tone ? "stat-warn" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ValidationSection() {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (report || loading) return;
    setLoading(true);
    try {
      setReport(await api.validation());
    } catch (err) {
      setError(message(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="validation">
      <div className="validation-head">
        <div>
          <span className="eyebrow">Retrospective validation</span>
          <h2>Does the ranking actually work?</h2>
          <p>
            Cases run untuned, misses included. Each is compared with the same
            pipeline minus docking, and with random orderings of the same
            candidates, so a good number has to beat both.
          </p>
        </div>
        <button type="button" className="btn btn-outline" onClick={load}>
          {loading ? "Running cases…" : report ? "Reload" : "Show validation results"}
        </button>
      </div>

      {error && <div className="notice notice-warn">{error}</div>}

      {report && (
        <>
          <div className="stats stats-wide">
            <Stat label="Cases" value={report.aggregate.n_cases} />
            <Stat
              label="Actives found"
              value={`${report.aggregate.n_actives_found}/${report.aggregate.n_actives}`}
            />
            <Stat label="Mean MRR" value={report.aggregate.mean_mrr.toFixed(3)} />
            <Stat
              label="Annotation only"
              value={report.aggregate.mean_mrr_annotation_only.toFixed(3)}
            />
            <Stat
              label="Corpus bias"
              value={pct(report.corpus_bias.fraction)}
              tone="warn"
            />
          </div>

          <div className="table-wrap">
            <table className="shortlist validation-table">
              <thead>
                <tr>
                  <th>Case</th>
                  <th className="right">Actives</th>
                  <th className="right">MRR</th>
                  <th className="right">No docking</th>
                  <th className="right">Δ</th>
                  <th className="right">Random MRR</th>
                  <th className="right">p</th>
                  <th className="right">Six-cohort in top 10</th>
                </tr>
              </thead>
              <tbody>
                {report.cases.map((item) => (
                  <tr key={item.case} className="row">
                    <td>{item.label}</td>
                    <td className="right num">
                      {item.metrics.n_found}/{item.metrics.n_known_actives}
                    </td>
                    <td className="right num">{item.metrics.mrr.toFixed(3)}</td>
                    <td className="right num">
                      {item.ablation.annotation_only.mrr.toFixed(3)}
                    </td>
                    <td className="right num">
                      {item.ablation.delta_mrr >= 0 ? "+" : ""}
                      {item.ablation.delta_mrr.toFixed(3)}
                    </td>
                    <td className="right num">
                      {item.null_baseline.random_mrr_mean?.toFixed(3) ?? "—"}
                    </td>
                    <td className="right num">
                      {item.null_baseline.p_value_mrr?.toFixed(3) ?? "—"}
                    </td>
                    <td className="right num">{item.bias_residue.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="fineprint validation-note">
            Corpus bias: {report.corpus_bias.topped_by_six.toLocaleString()} of{" "}
            {report.corpus_bias.eligible_groups.toLocaleString()} plant–part groups
            with ≥3 candidates are topped by {report.corpus_bias.six_compounds.join(", ")}.
            Agreement with the literature is a check on the ranking, not a prospective
            validation.
          </p>
        </>
      )}
    </section>
  );
}
