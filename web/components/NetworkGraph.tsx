"use client";

import { useMemo, useState } from "react";
import type { Network } from "@/lib/types";

interface Props {
  network: Network | null;
  selectedCompoundId?: string;
  onSelectCompound?: (compoundId: string) => void;
}

export default function NetworkGraph({
  network,
  selectedCompoundId,
  onSelectCompound,
}: Props) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const layout = useMemo(() => {
    if (!network || network.nodes.length === 0) return null;

    const width = 640;
    const height = 310;
    const padY = 26;

    const compounds = network.nodes
      .filter((n) => n.type === "compound")
      .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99))
      .slice(0, 10);

    const conditionNode =
      network.nodes.find((n) => n.type === "condition") ?? {
        id: "condition:root",
        label: "Condition",
        type: "condition",
      };

    // Rank targets by degree among the top compounds
    const compIds = new Set(compounds.map((c) => c.id));
    const deg = new Map<string, number>();
    for (const e of network.edges) {
      if (compIds.has(e.source) && e.target.startsWith("target:")) {
        deg.set(e.target, (deg.get(e.target) ?? 0) + 1);
      }
    }

    const targets = network.nodes
      .filter((n) => n.type === "target" && deg.has(n.id))
      .sort((a, b) => (deg.get(b.id) ?? 0) - (deg.get(a.id) ?? 0) || a.label.localeCompare(b.label))
      .slice(0, 12);

    const pos = new Map<string, { x: number; y: number; label: string; type: string; rank?: number }>();

    compounds.forEach((c, i) => {
      const y =
        compounds.length === 1
          ? height / 2
          : padY + (i * (height - padY * 2)) / (compounds.length - 1);
      pos.set(c.id, { x: 138, y, label: c.label, type: "compound", rank: c.rank });
    });

    targets.forEach((t, i) => {
      const y =
        targets.length === 1
          ? height / 2
          : padY + (i * (height - padY * 2)) / (targets.length - 1);
      pos.set(t.id, { x: 382, y, label: t.label, type: "target" });
    });

    pos.set(conditionNode.id, {
      x: 556,
      y: height / 2,
      label: conditionNode.label,
      type: "condition",
    });

    // Deduplicate edges visible in this layout
    const seen = new Set<string>();
    const edges: {
      key: string;
      source: string;
      target: string;
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      measured: boolean;
    }[] = [];

    for (const e of network.edges) {
      const s = pos.get(e.source);
      const t = pos.get(e.target);
      if (!s || !t) continue;
      const k = `${e.source}->${e.target}`;
      if (seen.has(k)) continue;
      seen.add(k);
      edges.push({
        key: k,
        source: e.source,
        target: e.target,
        x1: s.x,
        y1: s.y,
        x2: t.x,
        y2: t.y,
        measured: e.measured,
      });
    }

    return { width, height, nodes: Array.from(pos.entries()), edges };
  }, [network]);

  if (!network || !layout) return null;

  const activeNodeId =
    hoveredId ?? (selectedCompoundId ? `compound:${selectedCompoundId}` : null);

  return (
    <div className="card network-card">
      <div className="network-head">
        <div>
          <span className="eyebrow">Mechanism Topology</span>
          <h3>Compound → Target → Condition Network</h3>
        </div>
        <div className="network-legend">
          <span>
            <i className="leg-line leg-measured" /> Measured (ChEMBL/BindingDB)
          </span>
          <span>
            <i className="leg-line leg-predicted" /> Predicted (NPASS)
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="network-svg"
        role="img"
        aria-label="Compound to target to disease bipartite network graph"
      >
        <g className="network-edges">
          {layout.edges.map((e) => {
            const highlighted =
              !activeNodeId || e.source === activeNodeId || e.target === activeNodeId;
            return (
              <path
                key={e.key}
                d={`M ${e.x1} ${e.y1} C ${(e.x1 + e.x2) / 2} ${e.y1}, ${(e.x1 + e.x2) / 2} ${e.y2}, ${e.x2} ${e.y2}`}
                fill="none"
                stroke={e.measured ? "#1b5e46" : "#b87924"}
                strokeWidth={highlighted && activeNodeId ? 1.8 : 1.1}
                strokeDasharray={e.measured ? undefined : "4 3"}
                opacity={highlighted ? (activeNodeId ? 0.85 : 0.45) : 0.12}
              />
            );
          })}
        </g>

        <g className="network-nodes">
          {layout.nodes.map(([id, n]) => {
            const isSelected =
              id === activeNodeId || id === `compound:${selectedCompoundId}`;
            const fill =
              n.type === "compound"
                ? isSelected
                  ? "#1b5e46"
                  : "#2f7d61"
                : n.type === "target"
                  ? "#1f4c7a"
                  : "#9a621c";
            const r = n.type === "condition" ? 11 : n.type === "compound" ? 7.5 : 6.5;
            const short =
              n.label.length > 21 ? `${n.label.slice(0, 20)}…` : n.label;

            return (
              <g
                key={id}
                transform={`translate(${n.x}, ${n.y})`}
                className="network-node"
                onMouseEnter={() => setHoveredId(id)}
                onMouseLeave={() => setHoveredId(null)}
                onClick={() => {
                  if (n.type === "compound" && onSelectCompound) {
                    onSelectCompound(id.replace(/^compound:/, ""));
                  }
                }}
                style={{ cursor: n.type === "compound" ? "pointer" : "default" }}
              >
                <circle
                  r={r}
                  fill={fill}
                  stroke="#fffdf8"
                  strokeWidth={isSelected ? 2.5 : 1.5}
                />
                <text
                  x={n.type === "compound" ? -11 : n.type === "target" ? 10 : 0}
                  y={n.type === "condition" ? -16 : 3.5}
                  textAnchor={
                    n.type === "compound"
                      ? "end"
                      : n.type === "target"
                        ? "start"
                        : "middle"
                  }
                  className="network-label"
                  fontWeight={isSelected ? 650 : 500}
                >
                  {n.type === "compound" && n.rank ? `#${n.rank} ${short}` : short}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <p className="fineprint">
        Hover any node to trace its pathway; click a compound node to load its 3D receptor pose above.
      </p>
    </div>
  );
}
