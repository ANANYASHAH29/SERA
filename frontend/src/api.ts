const BASE = "/api";
const BACKEND_ORIGIN = "http://127.0.0.1:8000";

export interface RunSummary {
  run_id: number;
  accuracy: number;
  mean_confidence: number;
  mean_entropy: number;
  is_baseline: boolean;
}

export interface IncidentSummary {
  incident_id: number;
  baseline_run_id: number;
  regressed_run_id: number;
  accuracy_drop: number;
  status: string;
}

export interface RankedCandidateOut {
  rank: number;
  candidate_id: string;
  kind: "commit" | "drift";
  hypothesized_category: string | null;
  provenance_score: number;
  shape_match_score: number;
  combined_score: number;
  commit_sha: string | null;
  commit_message: string | null;
  commit_files: string[] | null;
}

export interface RankingResponse {
  incident_id: number;
  observed_shape: { broadness: number; subset_concentration: number; confident_but_wrong: number };
  candidates: RankedCandidateOut[];
}

export interface ValidationResponse {
  incident_id: number;
  candidate_id: string;
  kind: string;
  before_accuracy: number;
  after_accuracy: number;
  baseline_accuracy: number;
  recovered: boolean;
  confirmed: boolean;
}

export interface AccuracySummaryRow {
  method: string;
  n_trials: number;
  top1_accuracy: number;
  top1_ci_low: number;
  top1_ci_high: number;
  top2_accuracy: number;
  top2_ci_low: number;
  top2_ci_high: number;
}

export interface CostComparisonRow {
  method: string;
  top1_accuracy: number;
  top2_accuracy: number;
  mean_reevaluations: number;
  max_reevaluations: number;
  total_reevaluations: number;
  n_trials: number;
  reevals_vs_sera?: number;
}

export interface ConfusionMatrix {
  labels: string[];
  conditions: string[];
  matrix: number[][];
}

export interface ExperimentsSummary {
  accuracy_summary: AccuracySummaryRow[];
  cost_comparison: CostComparisonRow[];
  confusion_matrices: Record<string, ConfusionMatrix>;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${options?.method ?? "GET"} ${path} -> ${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  createBaselineRun: (seed = 0) =>
    request<RunSummary>(`/runs/baseline?seed=${seed}`, { method: "POST" }),

  createInjectedRun: (condition: string, severity: number, seed = 0) =>
    request<RunSummary>(`/runs/inject`, {
      method: "POST",
      body: JSON.stringify({ condition, severity, seed }),
    }),

  detectIncident: (baselineRunId: number, regressedRunId: number) =>
    request<IncidentSummary>(
      `/incidents/detect?baseline_run_id=${baselineRunId}&regressed_run_id=${regressedRunId}`,
      { method: "POST" }
    ),

  attachSyntheticHistory: (
    incidentId: number,
    params: {
      num_harmless: number;
      guilty_category: string | null;
      include_concurrent_unrelated: boolean;
      window_hours: number;
      seed: number;
    }
  ) =>
    request<{ incident_id: number; num_commits: number }>(
      `/incidents/${incidentId}/history/synthetic`,
      { method: "POST", body: JSON.stringify(params) }
    ),

  attachGithubHistory: (
    incidentId: number,
    params: { repo_full_name: string; since: string; until: string; token?: string }
  ) =>
    request<{ incident_id: number; num_commits: number }>(
      `/incidents/${incidentId}/history/github`,
      { method: "POST", body: JSON.stringify(params) }
    ),

  rankIncident: (incidentId: number) =>
    request<RankingResponse>(`/incidents/${incidentId}/rank`, { method: "POST" }),

  validateIncident: (incidentId: number) =>
    request<ValidationResponse>(`/incidents/${incidentId}/validate`, { method: "POST" }),

  experimentsSummary: () => request<ExperimentsSummary>(`/experiments/summary`),
};

export const RESULTS_STATIC_BASE = `${BACKEND_ORIGIN}/results-static`;
