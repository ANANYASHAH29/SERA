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

export type HealthStatus = "healthy" | "incident" | "pending" | "never_scanned";

export interface ConnectedRepoOut {
  id: number;
  repo_full_name: string;
  sera_yml_status: "missing" | "present" | "invalid";
  connected_at: string;
  last_scan_at: string | null;
  health_status: HealthStatus;
  incident_count: number;
}

export interface ScanResultOut {
  id: number;
  run_id: number | null;
  status: string;
  summary_json: string | null;
  created_at: string;
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

  // --- Phase 3: multi-tenant "connect your repo" ---
  installUrl: () => request<{ install_url: string }>(`/tenant/install-url`),

  userByInstallation: (installationId: number) =>
    request<{ user_id: number; github_username: string }>(
      `/tenant/users/by-installation/${installationId}`
    ),

  availableRepos: (installationId: number) =>
    request<string[]>(`/tenant/installations/${installationId}/available-repos`),

  listConnectedRepos: (userId: number) =>
    request<ConnectedRepoOut[]>(`/tenant/repos?user_id=${userId}`),

  connectRepo: (userId: number, repoFullName: string) =>
    request<ConnectedRepoOut>(`/tenant/repos`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, repo_full_name: repoFullName }),
    }),

  disconnectRepo: (userId: number, repoId: number) =>
    request<{ status: string }>(`/tenant/repos/${repoId}?user_id=${userId}`, {
      method: "DELETE",
    }),

  seraYmlTemplate: (userId: number, repoId: number) =>
    request<{ template: string }>(`/tenant/repos/${repoId}/sera-yml-template?user_id=${userId}`),

  repoScans: (userId: number, repoId: number) =>
    request<ScanResultOut[]>(`/tenant/repos/${repoId}/scans?user_id=${userId}`),

  badgeMarkdown: (userId: number, repoId: number) =>
    request<{ markdown: string; badge_url: string }>(
      `/tenant/repos/${repoId}/badge-markdown?user_id=${userId}&base_url=${encodeURIComponent(BACKEND_ORIGIN)}`
    ),

  runDemoScan: (userId: number, repoId: number, condition: string | null, seed = 0) =>
    request<{ scan_id: number; status: string; baseline_accuracy: number; regressed_accuracy: number }>(
      `/tenant/repos/${repoId}/scan?user_id=${userId}`,
      { method: "POST", body: JSON.stringify({ condition, seed }) }
    ),

  reportToken: (userId: number, repoId: number) =>
    request<{ report_token: string; report_url: string }>(
      `/tenant/repos/${repoId}/report-token?user_id=${userId}&base_url=${encodeURIComponent(BACKEND_ORIGIN)}`
    ),
};

export const RESULTS_STATIC_BASE = `${BACKEND_ORIGIN}/results-static`;
