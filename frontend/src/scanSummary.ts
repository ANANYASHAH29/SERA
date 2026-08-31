import type { InterventionResult, RankedCandidateOut } from "./api";

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
 */
export function describeLikelyCause(summary: ParsedScanSummary): LikelyCause | null {
  const top = summary.candidates[0];
  if (!top) return null;

  if (top.kind === "commit") {
    const stage = top.stage_label ?? top.hypothesized_category;
    return {
      title: `likely cause: commit ${top.commit_sha?.slice(0, 8) ?? "unknown"}`,
      body:
        `This commit touches a file in the "${stage}" stage of the pipeline, and the ` +
        `observed confidence/entropy shift matches that failure pattern (combined evidence score ` +
        `${top.combined_score.toFixed(2)} vs. the next candidate). ${top.commit_message ?? ""}`.trim(),
    };
  }

  const confidentButWrong = summary.observedShape?.confident_but_wrong ?? 0;
  if (confidentButWrong > 0.5) {
    return {
      title: "likely cause: possible data integrity issue",
      body:
        "Accuracy dropped sharply while confidence stayed high — the model is confidently wrong, " +
        "not uncertain. This pattern often indicates a labeling error or data tampering rather than " +
        "gradual natural drift. No recent commit explains the change.",
    };
  }

  return {
    title: "likely cause: genuine data drift",
    body:
      "No recent commit touches a risk-category file, and the confidence pattern is consistent with " +
      "the input distribution shifting since deployment rather than a code change.",
  };
}
