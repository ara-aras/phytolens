export type PlantHit = {
  id: string;
  plant: string;
  common_name: string | null;
  matched: string;
};

export type Part = { part: string; compounds: number };

export type Gene = {
  symbol: string;
  condition_score: number | null;
  measured: boolean;
  evidence: Record<string, unknown>;
};

export type Ranked = {
  rank: number;
  id: string;
  name: string;
  score: number;
  mw: number | null;
  logp: number | null;
  flags: string[];
  targets: { annotated: number; measured: number };
  overlap: { count: number; measured: number; genes: Gene[] };
  terms: Record<string, number>;
  contributions: Record<string, number>;
  docking: Record<string, number>;
  docking_missing: boolean;
};

export type Shortlist = {
  run_id?: string;
  demo?: boolean;
  condition: {
    id: string;
    name: string;
    targets: number;
    source: string;
    retrieved: string;
    min_score: number;
  };
  formulation: {
    plant: string;
    plant_id: string;
    part: string;
    solvent: string;
    solvent_label: string;
  };
  config_hashes: { extraction: string; ranking: string };
  docking_pending: boolean;
  docking: { candidates: number; docked: number; partial: boolean };
  docking_targets?: string[];
  funnel: {
    in_part: number;
    pass_extraction: number;
    flagged_druglikeness: number;
    with_condition_target: number;
    excluded_no_condition_target: number;
  };
  ranked: Ranked[];
};

export type RunStatus = {
  run_id: string;
  status: "queued" | "running" | "complete" | "failed";
  stage: string;
  progress: number;
  request: { plant: string; part: string; solvent: string; condition: string; top: number };
  error: string | null;
  queue?: string;
};

export type Health = {
  status: string;
  version: string;
  corpus: { plants: number; compounds: number; plant_compounds: number; compound_targets: number };
  conditions: string[];
  docking_panel: string | null;
  vina: string;
  queue: {
    backend: string;
    depth?: number;
    redis?: string | null;
    worker_alive?: boolean;
  };
  auth: { enabled: boolean };
};

export type Network = {
  nodes: { id: string; label: string; type: string; rank?: number }[];
  edges: { source: string; target: string; measured: boolean }[];
  hubs: { id: string; label: string; degree: number }[];
};

export type ValidationMetrics = {
  n_known_actives: number;
  n_found: number;
  mrr: number;
  recall_at_10: number;
  recall_at_25: number;
  best_rank: number | null;
  mean_rank: number | null;
  ranks: Record<string, number>;
};

export type ValidationCase = {
  case: string;
  label: string;
  metrics: ValidationMetrics;
  ablation: {
    annotation_only: ValidationMetrics;
    delta_mrr: number;
  };
  null_baseline: {
    permutations?: number;
    random_mrr_mean?: number;
    p_value_mrr?: number;
    mrr_percentile?: number;
    analytic_expected_mrr?: number;
  };
  bias_residue: { count: number; six_in_top: string[] };
  run: { docking: { docked: number; candidates: number } };
  top_10: { rank: number; name: string }[];
};

export type ValidationReport = {
  docking_used: boolean;
  aggregate: {
    n_cases: number;
    mean_mrr: number;
    mean_mrr_annotation_only: number;
    delta_mrr: number;
    n_actives_found: number;
    n_actives: number;
  };
  corpus_bias: {
    topped_by_six: number;
    eligible_groups: number;
    fraction: number;
    six_compounds: string[];
  };
  cases: ValidationCase[];
};

export type LiveDockResult = {
  fresh: number;
  reused: number;
  skipped_no_smiles: string[];
  engine: string;
  vina: string;
  shortlist: Ranked[];
  docking: { candidates: number; docked: number; partial: boolean };
  docked: Record<string, { name: string; targets: Record<string, { affinity: number | null; seconds: number; cached: boolean }> }>;
};
