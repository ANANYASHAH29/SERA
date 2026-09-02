import type { InterventionAttempt, InterventionResult, InterventionVerdict, RankedCandidateOut } from "./api";

export interface ParsedScanSummary {
  primaryMetricName: string;
  baselineMetric: number;
  currentMetric: number;
  metricDrop: number;
  meanConfidence: number | null;
  meanEntropy: number | null;
  observedShape: { broadness: number; subset_concentration: number; confident_but_wrong: number } | null;
  candidates: RankedCandidateOut[];
  source: string;
  windowSince: string | null;
  commitsAnalyzed: number;
  commitsRelevant: number;
  taskType: string | null;
}

/** Reads either ingestion path's summary_json shape defensively --
 * /report uses baseline_accuracy/regressed_accuracy/accuracy_drop,
 * /ingest-scan-result uses baseline_metric/current_metric/metric_drop.
 */
export function parseScanSummary(raw: string | null): ParsedScanSummary | null {
  if (!raw) return null;
  try {
    const d = JSON.parse(raw);
    return {
      primaryMetricName: d.primary_metric_name ?? "accuracy",
      baselineMetric: d.baseline_metric ?? d.baseline_accuracy ?? 0,
      currentMetric: d.current_metric ?? d.regressed_accuracy ?? 0,
      metricDrop: d.metric_drop ?? d.accuracy_drop ?? 0,
      meanConfidence: d.secondary_metrics?.mean_confidence ?? null,
      meanEntropy: d.secondary_metrics?.mean_entropy ?? null,
      observedShape: d.observed_shape ?? null,
      candidates: d.candidates ?? [],
      source: d.source ?? "manual",
      windowSince: d.window_since ?? null,
      commitsAnalyzed: d.commits_analyzed ?? 0,
      commitsRelevant: d.commits_relevant ?? 0,
      taskType: d.task_type ?? null,
    };
  } catch {
    return null;
  }
}

export function parseValidation(raw: string | null): InterventionResult | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as InterventionResult;
  } catch {
    return null;
  }
}

/** The full sequential-validation attempt list, when the tenant's CI
 * tested more than one candidate (or a combined revert) -- see
 * sera.method.validation.record_interventions. Empty if only the
 * single-attempt /validate-scan path was used (or nothing reported yet).
 */
export function parseInterventions(raw: string | null): InterventionAttempt[] {
  if (!raw) return [];
  try {
    return JSON.parse(raw) as InterventionAttempt[];
  } catch {
    return [];
  }
}

const VERDICT_LABEL: Record<InterventionVerdict, string> = {
  validated: "VALIDATED",
  validated_combined: "VALIDATED (COMBINED)",
  insufficient_as_sole_cause: "INSUFFICIENT AS SOLE CAUSE",
  insufficient_combined: "INSUFFICIENT (COMBINED)",
  not_supported: "NOT SUPPORTED",
};

const VERDICT_EXPLANATION: Record<InterventionVerdict, string> = {
  validated: "Reverting this commit alone restored the healthy baseline.",
  validated_combined:
    "None of the contributing commits alone restored the baseline, but reverting all of them together did.",
  insufficient_as_sole_cause:
    "Reverting this commit alone improved accuracy but did not restore the healthy baseline. Other validated contributing changes may remain -- this is not evidence the commit is unrelated.",
  insufficient_combined:
    "Reverting every commit that showed individual improvement, together, still did not restore the baseline.",
  not_supported:
    "Reverting this commit alone produced no measurable improvement. In a single-cause incident this would rule it out; in a multi-fault incident it does not, on its own, prove the commit is unrelated.",
};

export function verdictLabel(verdict: InterventionVerdict): string {
  return VERDICT_LABEL[verdict] ?? verdict.toUpperCase();
}

export function verdictExplanation(verdict: InterventionVerdict): string {
  return VERDICT_EXPLANATION[verdict] ?? "";
}

const SOURCE_LABEL: Record<string, string> = {
  ci: "automated / CI",
  manual: "manual / paste-in",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source;
}

export interface WhatChanged {
  commitSha: string;
  commitMessage: string | null;
  commitAuthor: string | null;
  stageLabel: string | null;
  files: { path: string; patch: string | null }[];
}

/** "What changed" data for the top candidate, when it's a real commit --
 * files touched plus (when the file is text, not binary) the actual diff
 * text GitHub already returned, so the dashboard can show the specific
 * lines that changed instead of just a filename.
 */
export function describeWhatChanged(summary: ParsedScanSummary): WhatChanged | null {
  const top = summary.candidates[0];
  if (!top || top.kind !== "commit" || !top.commit_sha) return null;
  const files = top.commit_files ?? [];
  return {
    commitSha: top.commit_sha,
    commitMessage: top.commit_message,
    commitAuthor: top.commit_author,
    stageLabel: top.stage_label,
    files: files.map((path) => ({ path, patch: top.commit_file_patches?.[path] ?? null })),
  };
}

export function timeAgo(isoString: string): string {
  const then = new Date(isoString).getTime();
  const now = Date.now();
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export interface LikelyCause {
  title: string;
  body: string;
}

/** Generates the "likely cause" narrative from the top-ranked candidate +
 * observed shape signals -- never fabricates a specific commit/category
 * that the ranking didn't actually produce.
 *
 * `validated` reflects actual epistemic status, not just a ranking: a
 * commit is a "top-ranked hypothesis" until the CI-driven intervention
 * confirms recovery, at which point it becomes a "validated culprit" --
 * ranking alone is not proof, and the wording says so.
 */
export function describeLikelyCause(summary: ParsedScanSummary, validated?: boolean): LikelyCause | null {
  const top = summary.candidates[0];
  if (!top) return null;

  if (top.kind === "commit") {
    const stage = top.stage_label ?? top.hypothesized_category;
    const verdict = validated ? "Validated culprit" : "Top-ranked hypothesis";
    return {
      title: `${verdict}: commit ${top.commit_sha?.slice(0, 8) ?? "unknown"}`,
      body:
        `This commit touches a file in the "${stage}" stage of the pipeline, and the ` +
        `observed confidence/entropy shift matches that failure pattern (combined evidence score ` +
        `${top.combined_score.toFixed(2)} vs. the next candidate). ${top.commit_message ?? ""}`.trim(),
    };
  }

  const confidentButWrong = summary.observedShape?.confident_but_wrong ?? 0;
  if (confidentButWrong > 0.5) {
    return {
      title: "Top hypothesis: possible data integrity issue",
      body:
        "Accuracy dropped sharply while confidence stayed high — the model is confidently wrong, " +
        "not uncertain. This pattern often indicates a labeling error or data tampering rather than " +
        "gradual natural drift. No commit in the analyzed window explains the change.",
    };
  }

  return {
    title: "Top hypothesis: genuine data drift (no commit)",
    body:
      "No commit in the analyzed window touches a risk-category file with a matching evidence shape. " +
      "The confidence/entropy pattern is consistent with the input distribution shifting since " +
      "deployment rather than a code change — SERA is not manufacturing a culprit commit here.",
  };
}
