"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { DockingPose, Ranked } from "@/lib/types";

const TARGET_LABELS: Record<string, { title: string; pdb: string; role: string }> = {
  PTGS2: { title: "COX-2", pdb: "3NT1", role: "Prostaglandin G/H synthase 2" },
  ALOX5: { title: "5-LOX", pdb: "3V99", role: "Arachidonate 5-lipoxygenase (Fe²⁺)" },
  MAPK14: { title: "p38-α", pdb: "3D83", role: "Mitogen-activated protein kinase 14" },
  TNF: { title: "TNF-α", pdb: "2AZ5", role: "Tumor necrosis factor homodimer" },
};

const pdbTextCache = new Map<string, string>();

interface Props {
  ranked: Ranked[];
  targets: string[];
  selectedCompoundId: string;
  onSelectCompound: (compoundId: string) => void;
}

export default function DockingStudio({
  ranked,
  targets,
  selectedCompoundId,
  onSelectCompound,
}: Props) {
  const availableTargets = useMemo(() => {
    const base = targets.length > 0 ? targets : ["PTGS2", "ALOX5", "MAPK14"];
    return base.includes("TNF") ? base : [...base, "TNF"];
  }, [targets]);

  const selectedCompound = useMemo(
    () => ranked.find((r) => r.id === selectedCompoundId) ?? ranked[0] ?? null,
    [ranked, selectedCompoundId],
  );

  const [selectedTarget, setSelectedTarget] = useState<string>("PTGS2");
  const [selectedModeIdx, setSelectedModeIdx] = useState<number>(0);
  const [pose, setPose] = useState<DockingPose | null>(null);
  const [loadingPose, setLoadingPose] = useState<boolean>(false);
  const [poseError, setPoseError] = useState<string | null>(null);

  const [focusMode, setFocusMode] = useState<"pocket" | "protein">("pocket");
  const [showSurface, setShowSurface] = useState<boolean>(true);
  const [showBox, setShowBox] = useState<boolean>(true);
  const [spinning, setSpinning] = useState<boolean>(false);
  const [fullscreen, setFullscreen] = useState<boolean>(false);

  const viewportRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<any>(null);
  const ligandCompRef = useRef<any>(null);
  const proteinCompRef = useRef<any>(null);

  // Pick the strongest docked target when switching compounds if current target has no score
  useEffect(() => {
    if (!selectedCompound) return;
    const d = selectedCompound.docking ?? {};
    if (d[selectedTarget] != null) return;
    const best = Object.entries(d).sort((a, b) => a[1] - b[1])[0]?.[0];
    if (best) setSelectedTarget(best);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompound?.id]);

  // Fetch 3D pose + modes + contacts + 2D SVG when (compound, target) changes
  useEffect(() => {
    if (!selectedCompound || !selectedTarget) return;
    let cancelled = false;
    setLoadingPose(true);
    setPoseError(null);
    setSelectedModeIdx(0);

    api
      .dockingPose(selectedCompound.id, selectedTarget)
      .then((payload) => {
        if (cancelled) return;
        setPose(payload);
        setLoadingPose(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setPose(null);
        setPoseError(
          err instanceof Error
            ? err.message
            : "No precomputed 3D pose cached for this compound/target pair.",
        );
        setLoadingPose(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedCompound, selectedTarget]);

  const activeMode = pose?.modes?.[selectedModeIdx] ?? pose?.modes?.[0] ?? null;

  // Render 3D scene in NGL
  useEffect(() => {
    if (typeof window === "undefined" || !viewportRef.current || !pose || !activeMode) {
      return;
    }

    let cancelled = false;
    let stage: any = null;
    let resizeHandler: (() => void) | null = null;

    import("ngl").then(async (NGL) => {
      if (cancelled || !viewportRef.current) return;

      stage = new NGL.Stage(viewportRef.current, {
        backgroundColor: "#101b16",
        tooltip: true,
        sampleLevel: 0,
      });
      stageRef.current = stage;

      resizeHandler = () => {
        try {
          stage?.handleResize();
        } catch {
          /* ignore */
        }
      };
      window.addEventListener("resize", resizeHandler);

      try {
        // 1. Load receptor PDB (cached in memory per target)
        let pdbText = pdbTextCache.get(pose.target);
        if (!pdbText) {
          const resp = await fetch(api.structurePdbUrl(pose.target));
          if (resp.ok) {
            pdbText = await resp.text();
            pdbTextCache.set(pose.target, pdbText);
          }
        }
        if (cancelled || !stage) return;

        let proteinComp: any = null;
        if (pdbText) {
          const pdbBlob = new Blob([pdbText], { type: "text/plain" });
          proteinComp = await stage.loadFile(pdbBlob, {
            ext: "pdb",
            name: `${pose.pdb_id}.pdb`,
          });
          proteinCompRef.current = proteinComp;

          proteinComp.addRepresentation("cartoon", {
            colorScheme: "residueindex",
            opacity: 0.76,
            quality: "high",
          });

          // Highlight active-site contact residues (< 4.5 A)
          const contactResIds = pose.contacts
            .filter((c) => !c.is_cofactor)
            .map((c) => `${c.resid}:${c.chain}`);
          if (contactResIds.length > 0) {
            const sele = contactResIds.join(" or ");
            proteinComp.addRepresentation("licorice", {
              sele,
              colorScheme: "element",
              scale: 1.15,
              opacity: 0.92,
            });
            if (showSurface) {
              proteinComp.addRepresentation("surface", {
                sele,
                surfaceType: "av",
                color: "#3f9c77",
                opacity: 0.24,
              });
            }
          }

          // Highlight catalytic cofactors (Fe2+ in 3V99, HEM in 3NT1)
          proteinComp.addRepresentation("spacefill", {
            sele: "FE2 or _Fe",
            color: "#f59e0b",
            scale: 0.85,
          });
        }

        if (cancelled || !stage) return;

        // 2. Draw 20 A docking box wireframe
        if (showBox && pose.box) {
          const [cx, cy, cz] = pose.box.center;
          const [sx, sy, sz] = pose.box.size;
          const hx = sx / 2;
          const hy = sy / 2;
          const hz = sz / 2;
          const corners: [number, number, number][] = [
            [cx - hx, cy - hy, cz - hz],
            [cx + hx, cy - hy, cz - hz],
            [cx + hx, cy + hy, cz - hz],
            [cx - hx, cy + hy, cz - hz],
            [cx - hx, cy - hy, cz + hz],
            [cx + hx, cy - hy, cz + hz],
            [cx + hx, cy + hy, cz + hz],
            [cx - hx, cy + hy, cz + hz],
          ];
          const edges: [number, number][] = [
            [0, 1], [1, 2], [2, 3], [3, 0],
            [4, 5], [5, 6], [6, 7], [7, 4],
            [0, 4], [1, 5], [2, 6], [3, 7],
          ];
          const shape = new NGL.Shape("docking-box");
          for (const [a, b] of edges) {
            shape.addCylinder(
              corners[a],
              corners[b],
              [0.32, 0.78, 0.58],
              0.11,
              "20A docking box",
            );
          }
          const boxComp = stage.addComponentFromObject(shape);
          boxComp.addRepresentation("buffer", { opacity: 0.55 });
        }

        // 3. Load docked ligand pose for the active Vina mode
        const ligBlob = new Blob([activeMode.pdb_block], { type: "text/plain" });
        const ligandComp = await stage.loadFile(ligBlob, {
          ext: "pdb",
          name: `${pose.compound_name}_mode${activeMode.mode}.pdb`,
        });
        ligandCompRef.current = ligandComp;

        ligandComp.addRepresentation("ball+stick", {
          colorScheme: "element",
          scale: 2.15,
          aspectRatio: 1.8,
          quality: "high",
        });

        stage.setSpin(spinning);
        if (focusMode === "pocket" && ligandComp) {
          ligandComp.autoView(350);
        } else if (proteinComp) {
          proteinComp.autoView(350);
        }
      } catch (err) {
        console.warn("NGL 3D render error:", err);
      }
    });

    return () => {
      cancelled = true;
      if (resizeHandler) window.removeEventListener("resize", resizeHandler);
      try {
        stage?.dispose();
      } catch {
        /* ignore */
      }
      if (viewportRef.current) {
        viewportRef.current.innerHTML = "";
      }
      stageRef.current = null;
    };
  }, [pose, activeMode, showSurface, showBox]);

  // Resize NGL canvas smoothly when toggling fullscreen + support Esc key to close
  useEffect(() => {
    const id = window.setTimeout(() => {
      try {
        stageRef.current?.handleResize();
      } catch {
        /* ignore */
      }
    }, 40);
    if (!fullscreen) return () => window.clearTimeout(id);

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setFullscreen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [fullscreen]);

  // Toggle spin without rebuilding the scene
  useEffect(() => {
    if (stageRef.current) {
      stageRef.current.setSpin(spinning);
    }
  }, [spinning]);

  if (!selectedCompound) return null;

  const targetMeta = TARGET_LABELS[selectedTarget] ?? {
    title: selectedTarget,
    pdb: pose?.pdb_id ?? "PDB",
    role: selectedTarget,
  };

  return (
    <>
      {fullscreen && (
        <div
          className="studio-backdrop"
          onClick={() => setFullscreen(false)}
          aria-hidden="true"
        />
      )}
      <section
        className={`card studio-card ${fullscreen ? "studio-fullscreen" : ""}`}
        aria-label="3D Molecular Docking Studio"
      >
        <div className="studio-head">
          <div>
            <span className="eyebrow">3D Molecular Docking &amp; Active-Site Studio</span>
            <h3 className="studio-title">
              <span>{selectedCompound.name}</span>
              <span className="studio-arrow">→</span>
              <span>
                {targetMeta.title} ({targetMeta.pdb})
              </span>
            </h3>
            <p className="meta">
              {pose
                ? `Co-crystal reference pocket: ${pose.complex_with} (${pose.ligand_code}) · ${pose.vina} · seed ${pose.seed} · exhaustiveness ${pose.exhaustiveness}`
                : targetMeta.role}
            </p>
          </div>

          <div className="studio-controls">
            <div className="studio-top-actions">
              <label className="studio-select-wrap">
                <span>Compound</span>
                <select
                  value={selectedCompound.id}
                  onChange={(e) => onSelectCompound(e.target.value)}
                >
                  {ranked.map((row) => (
                    <option key={row.id} value={row.id}>
                      #{row.rank} {row.name} ({row.score.toFixed(3)})
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className={fullscreen ? "btn btn-primary studio-close-btn" : "btn btn-ghost studio-close-btn"}
                onClick={() => setFullscreen((v) => !v)}
                title={fullscreen ? "Close fullscreen (Esc)" : "Expand 3D Studio to fullscreen"}
              >
                {fullscreen ? "✕ Exit Fullscreen (Esc)" : "⛶ Expand"}
              </button>
            </div>

          <div className="studio-targets" role="tablist" aria-label="Docking targets">
            {availableTargets.map((t) => {
              const aff = selectedCompound.docking?.[t];
              const active = t === selectedTarget;
              const info = TARGET_LABELS[t];
              return (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={`studio-tab ${active ? "active" : ""}`}
                  onClick={() => setSelectedTarget(t)}
                >
                  <strong>{info ? `${t} · ${info.pdb}` : t}</strong>
                  <span className="num">
                    {aff != null ? `${aff.toFixed(2)} kcal/mol` : "on-demand"}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="studio-grid">
        {/* Left: 3D WebGL Receptor + Docked Pose Canvas */}
        <div className="studio-stage-wrap">
          <div className="studio-hud-top">
            <span className="hud-pill">
              <strong>PDB {pose?.pdb_id ?? targetMeta.pdb}</strong> · {targetMeta.title}
            </span>
            {pose?.box && (
              <span className="hud-pill">
                Box {pose.box.size.join("×")} Å @ [{pose.box.center.map((n) => n.toFixed(1)).join(", ")}]
              </span>
            )}
            {activeMode && (
              <span className="hud-pill hud-pill-accent">
                Mode {activeMode.mode}/{pose?.modes.length ?? 1} ·{" "}
                <strong>{activeMode.affinity?.toFixed(2)} kcal/mol</strong>
              </span>
            )}
          </div>

          <div
            ref={viewportRef}
            className="studio-viewport"
            aria-label="Interactive 3D protein pocket and docked ligand canvas"
          />

          {loadingPose && (
            <div className="studio-overlay">
              <span>Loading 3D receptor pocket &amp; docked Vina modes…</span>
            </div>
          )}

          {!loadingPose && poseError && (
            <div className="studio-overlay studio-overlay-warn">
              <p>
                <strong>No precomputed 3D pose cached for {selectedCompound.name} on {selectedTarget}.</strong>
              </p>
              <p className="fineprint">
                Switch to a panel target (PTGS2, ALOX5, MAPK14) or run on-demand live AutoDock Vina.
              </p>
            </div>
          )}

          <div
            className="studio-hud-bottom"
            onMouseDown={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
          >
            {pose && pose.modes.length > 0 && (
              <div className="studio-modes" aria-label="Vina binding modes">
                <span className="hud-label">Vina Modes:</span>
                {pose.modes.slice(0, 9).map((m, idx) => (
                  <button
                    key={m.mode}
                    type="button"
                    className={`mode-btn ${idx === selectedModeIdx ? "active" : ""}`}
                    onClick={() => setSelectedModeIdx(idx)}
                    title={`Mode ${m.mode}: ${m.affinity?.toFixed(2)} kcal/mol (RMSD l.b. ${m.rmsd_lb?.toFixed(2)} Å)`}
                  >
                    M{m.mode} · {m.affinity?.toFixed(2)}
                  </button>
                ))}
              </div>
            )}

            <div className="studio-toggles">
              <button
                type="button"
                className={`hud-btn ${focusMode === "pocket" ? "active" : ""}`}
                onClick={() => {
                  const next = focusMode === "pocket" ? "protein" : "pocket";
                  setFocusMode(next);
                  if (next === "pocket" && ligandCompRef.current) {
                    ligandCompRef.current.autoView(400);
                  } else if (proteinCompRef.current) {
                    proteinCompRef.current.autoView(400);
                  }
                }}
              >
                {focusMode === "pocket" ? "Pocket Zoom" : "Full Protein"}
              </button>
              <button
                type="button"
                className={`hud-btn ${showSurface ? "active" : ""}`}
                onClick={() => setShowSurface((v) => !v)}
              >
                Pocket Surface
              </button>
              <button
                type="button"
                className={`hud-btn ${showBox ? "active" : ""}`}
                onClick={() => setShowBox((v) => !v)}
              >
                20 Å Box
              </button>
              <button
                type="button"
                className={`hud-btn ${spinning ? "active" : ""}`}
                onClick={() => setSpinning((v) => !v)}
              >
                {spinning ? "Spin: On" : "Spin: Off"}
              </button>
              <button
                type="button"
                className="hud-btn"
                onClick={() => setFullscreen((v) => !v)}
              >
                {fullscreen ? "Exit Fullscreen" : "Expand"}
              </button>
            </div>
          </div>
        </div>

        {/* Right: 2D Chemical Structure + Binding Telemetry + Pocket Contacts */}
        <div className="studio-side">
          <div className="studio-mol-card">
            <div className="studio-mol-head">
              <span className="eyebrow">2D Chemical Structure (RDKit)</span>
              <span className="num">Rank #{selectedCompound.rank}</span>
            </div>
            {pose?.svg_2d ? (
              <div
                className="studio-svg"
                // Safe: generated locally by RDKit MolDraw2DSVG in engine/pipeline/docking.py
                dangerouslySetInnerHTML={{ __html: pose.svg_2d }}
              />
            ) : (
              <div className="studio-svg-empty">2D depiction unavailable</div>
            )}
            <div className="studio-mol-props">
              <span>MW {selectedCompound.mw ?? "—"} Da</span>
              <span>logP {selectedCompound.logp != null ? selectedCompound.logp.toFixed(2) : "—"}</span>
              {selectedCompound.admet && (
                <>
                  <span>QED {selectedCompound.admet.qed ?? "—"}</span>
                  <span>GI: {selectedCompound.admet.gi_absorption}</span>
                  <span>
                    BBB:{" "}
                    {selectedCompound.admet.bbb_permeant == null
                      ? "—"
                      : selectedCompound.admet.bbb_permeant
                        ? "permeant"
                        : "no"}
                  </span>
                </>
              )}
            </div>
          </div>

          <div className="studio-metrics">
            <div className="studio-metric">
              <span>Vina Affinity (ΔG)</span>
              <strong className="affinity">
                {activeMode?.affinity != null
                  ? `${activeMode.affinity.toFixed(2)} kcal/mol`
                  : "—"}
              </strong>
            </div>
            <div className="studio-metric">
              <span>Ligand Efficiency</span>
              <strong>
                {pose?.ligand_efficiency != null
                  ? `${pose.ligand_efficiency.toFixed(3)} kcal/mol/HA`
                  : "—"}
              </strong>
            </div>
            <div className="studio-metric">
              <span>Intermolecular E</span>
              <strong>
                {activeMode?.inter_energy != null
                  ? `${activeMode.inter_energy.toFixed(2)} kcal/mol`
                  : "—"}
              </strong>
            </div>
            <div className="studio-metric">
              <span>Mode RMSD (l.b.)</span>
              <strong>
                {activeMode?.rmsd_lb != null ? `${activeMode.rmsd_lb.toFixed(2)} Å` : "0.00 Å"}
              </strong>
            </div>
          </div>

          <div className="studio-contacts">
            <h4>
              Active-Site Pocket Contacts (≤ 4.5 Å)
              <span>{pose?.contacts.length ?? 0} residues</span>
            </h4>
            {pose && pose.contacts.length > 0 ? (
              <div className="chips">
                {pose.contacts.map((c) => (
                  <span
                    key={`${c.chain}-${c.resname}-${c.resid}`}
                    className={`chip ${c.is_cofactor ? "chip-cofactor" : "chip-measured"}`}
                    title={
                      c.is_cofactor
                        ? `Catalytic cofactor ${c.label} at ${c.distance} Å from docked pose`
                        : `Pocket residue ${c.label} at ${c.distance} Å from docked pose`
                    }
                  >
                    {c.is_cofactor ? `★ ${c.label}` : c.label} · {c.distance.toFixed(2)} Å
                  </span>
                ))}
              </div>
            ) : (
              <p className="fineprint">Select a docked target to inspect pocket contacts.</p>
            )}
          </div>

          {selectedCompound.admet &&
            (selectedCompound.admet.pains_alerts.length > 0 ||
              selectedCompound.admet.brenk_alerts.length > 0) && (
              <div className="studio-alert-box">
                <strong>Assay / Structural Alerts (RDKit FilterCatalog):</strong>
                <span>
                  {[
                    ...selectedCompound.admet.pains_alerts.map((a) => `PAINS: ${a}`),
                    ...selectedCompound.admet.brenk_alerts.map((a) => `Brenk: ${a}`),
                  ].join(" · ")}
                </span>
              </div>
            )}
        </div>
        </div>
      </section>
    </>
  );
}
