import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { ConnectedRepoOut, ScanResultOut } from "../api";
import { useSession } from "../session";
import { RankingTable } from "../components/RankingTable";
import { AccuracyChart } from "../components/AccuracyChart";
import { ErrorBanner } from "../components/StepCard";
import { RecoveryPanel } from "../components/RecoveryPanel";
import {
  describeLikelyCause,
  describeWhatChanged,
  parseInterventions,
  parseScanSummary,
  parseValidation,
  sourceLabel,
  timeAgo,
  verdictExplanation,
  verdictLabel,
} from "../scanSummary";

const STATUS_DOT: Record<string, string> = {
  healthy: "bg-emerald-500",
  incident: "bg-red-500",
  pending: "bg-amber-500",
  never_scanned: "bg-slate-500",
};

const STATUS_LABEL: Record<string, string> = {
  healthy: "HEALTHY",
  incident: "DEGRADED",
  pending: "PENDING",
  never_scanned: "NOT YET SCANNED",
};

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-[#6B7280]">{children}</h2>;
}

type StepState = "done" | "warn" | "pending";

function CausalChain({ steps }: { steps: { label: string; state: StepState; current?: boolean }[] }) {
  const dotClass: Record<StepState, string> = {
    done: "bg-emerald-500",
    warn: "bg-amber-500",
    pending: "bg-[#D1D5DB]",
  };
  const textClass: Record<StepState, string> = {
    done: "text-[#111827]",
    warn: "text-amber-700",
    pending: "text-[#9CA3AF]",
  };
  return (
    <div className="mb-5 flex flex-wrap items-center gap-x-1 gap-y-2">
      {steps.map((s, i) => (
        <div key={s.label} className="flex items-center">
          {i > 0 && <span className="mx-1.5 text-[#D1D5DB]">→</span>}
          <span
            className={`flex items-center gap-1.5 whitespace-nowrap rounded px-1.5 py-1 text-[11px] font-bold uppercase tracking-wide ${
              s.current ? "bg-indigo-50 ring-1 ring-indigo-200" : ""
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${dotClass[s.state]}`} />
            <span className={s.current ? "text-[#4F46E5]" : textClass[s.state]}>{s.label}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function MetricCard({
  label,
  value,
  valueClassName = "text-[#111827]",
  detail,
  caption,
}: {
  label: string;
  value: string;
  valueClassName?: string;
  detail?: React.ReactNode;
  caption?: string;
}) {
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="text-[10px] font-bold uppercase tracking-widest text-[#6B7280]">{label}</div>
      <div className={`mt-1.5 text-3xl font-bold ${valueClassName}`}>{value}</div>
      {detail && <div className="mt-1 text-xs font-medium">{detail}</div>}
      {caption && <div className="mt-1 text-[11px] text-[#9CA3AF]">{caption}</div>}
    </div>
  );
}

export function RepoDetailPage() {
  const { id } = useParams();
  const { session } = useSession();
  const [repo, setRepo] = useState<ConnectedRepoOut | null>(null);
  const [scans, setScans] = useState<ScanResultOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session || !id) return;
    const repoId = parseInt(id, 10);
    api.listConnectedRepos(session.userId).then((repos) => setRepo(repos.find((r) => r.id === repoId) ?? null));
    api
      .repoScans(session.userId, repoId)
      .then(setScans)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [session, id]);

  if (!session) {
    return <p className="text-sm text-[#6B7280]">Not connected — go to the connect flow first.</p>;
  }
  if (error) return <ErrorBanner message={error} theme="light" />;
  if (!scans) return <p className="text-sm text-[#9CA3AF]">Loading…</p>;

  if (scans.length === 0) {
    return (
      <div>
        <div className="mb-4">
          <Link to="/" className="text-xs font-medium uppercase tracking-wide text-[#4F46E5] hover:underline">
            ← All repos
          </Link>
          <h1 className="mt-1 font-mono text-xl font-semibold text-[#111827]">
            {repo?.repo_full_name ?? `repo #${id}`}
          </h1>
        </div>
        <div className="rounded-lg border border-dashed border-[#E5E7EB] bg-white p-8 text-center text-sm text-[#9CA3AF]">
          No scans yet. Go to <Link to={`/repos/${id}/settings`} className="text-[#4F46E5] hover:underline">Settings</Link> to
          detect/submit your first real evaluation result.
        </div>
      </div>
    );
  }

  // scans arrives newest-first; oldest-first is what the chart/timeline need.
  const chronological = [...scans].reverse();
  const latest = scans[0];
  const latestSummary = parseScanSummary(latest.summary_json);
  const status = latest.status;

  const chartPoints = chronological
    .map((s) => {
      const summary = parseScanSummary(s.summary_json);
      if (!summary) return null;
      return { time: s.created_at, metric: summary.currentMetric, status: s.status };
    })
    .filter((p): p is { time: string; metric: number; status: string } => p !== null);

  const suspectCommit = latestSummary?.candidates[0];
  const validation = status === "incident" ? parseValidation(latest.validation_json) : null;
  const interventions = status === "incident" ? parseInterventions(latest.interventions_json) : [];
  // "Recovered" is a binary pass/fail from the backend (within threshold
  // of baseline). For display, split the failure case further: any real
  // improvement over the pre-intervention accuracy is INCONCLUSIVE
  // (the hypothesis explains PART of the regression -- worth keeping as
  // a live candidate), while no improvement at all is a clean REJECTED.
  const validationVerdict: "validated" | "inconclusive" | "rejected" | null = !validation
    ? null
    : validation.recovered
      ? "validated"
      : validation.before_metric != null && validation.after_metric > validation.before_metric + 0.01
        ? "inconclusive"
        : "rejected";
  const likelyCause =
    status === "incident" && latestSummary ? describeLikelyCause(latestSummary, validation?.recovered) : null;
  const whatChanged = status === "incident" && latestSummary ? describeWhatChanged(latestSummary) : null;
  // Only meaningful as an explanation for a real regression -- a healthy
  // scan can have a nonzero confident_but_wrong signal from noise alone
  // (a few samples flipped without moving overall accuracy past the
  // regression threshold), and surfacing the annotation there would wrongly
  // imply something's currently wrong when the status pill says otherwise.
  const confidentlyWrong = status === "incident" && (latestSummary?.observedShape?.confident_but_wrong ?? 0) > 0.5;
  const isLive = latestSummary?.source === "ci";
  const commitUrl = (sha: string) => `https://github.com/${repo?.repo_full_name}/commit/${sha}`;

  return (
    <div>
      <Link to="/" className="mb-4 inline-block text-xs font-medium uppercase tracking-wide text-[#4F46E5] hover:underline">
        ← All repos
      </Link>

      {/* Dark repo identity header */}
      <div className="rounded-lg bg-[#0B0D10] px-6 pb-9 pt-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[status] ?? STATUS_DOT.pending}`} />
            <h1 className="font-mono text-lg font-semibold text-white">{repo?.repo_full_name ?? `repo #${id}`}</h1>
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold tracking-widest ${
                status === "incident" ? "bg-red-950 text-red-300" : "bg-emerald-950 text-emerald-300"
              }`}
            >
              {STATUS_LABEL[status] ?? status}
            </span>
          </div>
          <Link to={`/repos/${id}/settings`} className="text-sm text-slate-400 hover:text-slate-200">
            Settings
          </Link>
        </div>
        <div className="mt-2 flex items-center gap-3 text-xs text-slate-400">
          {latestSummary?.taskType && <span className="uppercase tracking-wide">{latestSummary.taskType}</span>}
          {isLive && (
            <span className="flex items-center gap-1.5 text-emerald-400">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
              </span>
              MONITORING ACTIVE
            </span>
          )}
          <span>
            Last scan {timeAgo(latest.created_at)} · {sourceLabel(latestSummary?.source ?? "manual")}
          </span>
        </div>
      </div>

      {/* Metric cards, overlapping the dark header */}
      <div className="-mt-5 mb-8 grid grid-cols-2 gap-4 px-1 sm:grid-cols-4">
        <MetricCard
          label={latestSummary?.primaryMetricName ?? "accuracy"}
          value={latestSummary ? `${(latestSummary.currentMetric * 100).toFixed(1)}%` : "—"}
          valueClassName={status === "incident" ? "text-red-600" : "text-[#111827]"}
          detail={
            status === "incident" && latestSummary ? (
              <span className="text-red-500">↓ {(latestSummary.metricDrop * 100).toFixed(1)}pt</span>
            ) : undefined
          }
          caption={latestSummary ? `baseline ${(latestSummary.baselineMetric * 100).toFixed(1)}%` : undefined}
        />
        <MetricCard
          label="mean confidence"
          value={latestSummary?.meanConfidence != null ? latestSummary.meanConfidence.toFixed(2) : "—"}
          detail={confidentlyWrong ? <span className="text-amber-600">⚠ confidently wrong</span> : undefined}
        />
        <MetricCard label="last scan" value={timeAgo(latest.created_at)} caption={sourceLabel(latestSummary?.source ?? "manual")} />
        <MetricCard
          label="suspect commit"
          value={suspectCommit && suspectCommit.kind === "commit" ? suspectCommit.commit_sha?.slice(0, 7) ?? "—" : "—"}
          valueClassName="font-mono text-[#111827]"
          caption={
            suspectCommit && suspectCommit.kind === "commit"
              ? `${suspectCommit.stage_label ?? suspectCommit.hypothesized_category ?? ""}${
                  suspectCommit.commit_author ? ` · ${suspectCommit.commit_author}` : ""
                }`
              : undefined
          }
        />
      </div>

      <SectionLabel>Performance</SectionLabel>
      <div className="mb-8 rounded-lg border border-[#E5E7EB] bg-white p-6 shadow-sm">
        <AccuracyChart points={chartPoints} />
      </div>

      {likelyCause && whatChanged && (
        <>
          <SectionLabel>Active incident</SectionLabel>
          <CausalChain
            steps={[
              { label: "Commit", state: "done" },
              { label: "CI execution", state: "done" },
              { label: "Metric shift", state: "done" },
              { label: "Root-cause ranking", state: "done", current: !validation },
              { label: "Controlled intervention", state: validation ? "done" : "pending" },
              {
                label: "Validation",
                state: validationVerdict === null ? "pending" : validationVerdict === "validated" ? "done" : "warn",
                current: validation != null,
              },
            ]}
          />
          <div className="mb-8 rounded-lg border border-[#E5E7EB] border-l-4 border-l-red-500 bg-white p-6 shadow-sm">
            <div className="mb-1 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-red-600">🔴</span>
                <h3 className="text-base font-bold uppercase tracking-wide text-[#111827]">Pipeline degradation</h3>
              </div>
              <a
                href={`${commitUrl(whatChanged.commitSha)}/checks`}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-medium text-[#4F46E5] hover:underline"
              >
                View CI run ↗
              </a>
            </div>
            <p className="mb-3 text-sm font-medium text-[#111827]">
              {latestSummary?.primaryMetricName ?? "Accuracy"} dropped {(latestSummary!.baselineMetric * 100).toFixed(1)}% →{" "}
              {(latestSummary!.currentMetric * 100).toFixed(1)}%
            </p>

            <div className="mb-3 text-xs font-bold uppercase tracking-widest text-[#6B7280]">{likelyCause.title}</div>
            <p className="mb-4 text-sm text-[#374151]">{likelyCause.body}</p>

            <div className="grid grid-cols-2 gap-x-6 gap-y-1 border-t border-[#E5E7EB] pt-4 text-sm">
              <div className="text-[#6B7280]">Commit</div>
              <div className="font-mono text-[#111827]">
                <a href={commitUrl(whatChanged.commitSha)} target="_blank" rel="noreferrer" className="hover:underline">
                  {whatChanged.commitSha.slice(0, 10)}
                </a>
                {whatChanged.commitMessage && <span className="ml-2 font-sans text-[#6B7280]">— {whatChanged.commitMessage}</span>}
              </div>
              <div className="text-[#6B7280]">Branch</div>
              <div className="font-mono text-[#111827]">main</div>
              <div className="text-[#6B7280]">Author</div>
              <div className="text-[#111827]">{whatChanged.commitAuthor ?? "—"}</div>
              <div className="text-[#6B7280]">Stage</div>
              <div className="text-[#111827]">{whatChanged.stageLabel ?? "—"}</div>
              <div className="text-[#6B7280]">Evidence</div>
              <div className="text-[#111827]">{suspectCommit?.combined_score.toFixed(2) ?? "—"}</div>
            </div>

            <p className="mt-4 text-xs text-[#9CA3AF]">
              Analyzed {latestSummary!.commitsAnalyzed} commit{latestSummary!.commitsAnalyzed === 1 ? "" : "s"} since the
              last healthy scan
              {latestSummary!.windowSince && ` (${new Date(latestSummary!.windowSince).toLocaleString()})`} —{" "}
              {latestSummary!.commitsRelevant} touched a risk-category file
              {latestSummary!.commitsAnalyzed > latestSummary!.commitsRelevant &&
                `, ${latestSummary!.commitsAnalyzed - latestSummary!.commitsRelevant} excluded as non-ML-relevant`}
              .
            </p>
          </div>
        </>
      )}

      {whatChanged && (
        <>
          <SectionLabel>What changed</SectionLabel>
          <div className="mb-8">
            <div className="mb-3">
              <div className="mb-1 text-xs text-[#6B7280]">Modified</div>
              <ul className="space-y-2">
                {whatChanged.files.map((f) => (
                  <li key={f.path}>
                    <div className="font-mono text-sm text-[#111827]">• {f.path}</div>
                    {f.patch ? (
                      <pre className="mt-1 overflow-x-auto rounded bg-[#F7F8FA] p-2 text-xs text-[#374151]">{f.patch}</pre>
                    ) : (
                      <div className="ml-3 text-xs text-[#9CA3AF]">binary artifact — no text diff available</div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}

      {status === "incident" && whatChanged && (
        <>
          <SectionLabel>Validation{interventions.length > 1 ? ` — ${interventions.length} attempts` : ""}</SectionLabel>
          {interventions.length > 0 ? (
            <div className="mb-8 space-y-3">
              {interventions.map((a, i) => {
                const success = a.verdict === "validated" || a.verdict === "validated_combined";
                const insufficient = a.verdict === "insufficient_as_sole_cause" || a.verdict === "insufficient_combined";
                const borderClass = success ? "border-l-emerald-500" : insufficient ? "border-l-amber-500" : "border-l-[#D1D5DB]";
                return (
                  <div key={i} className={`rounded-lg border border-[#E5E7EB] border-l-4 bg-white p-5 shadow-sm ${borderClass}`}>
                    <div className="mb-2 flex items-center justify-between">
                      <div className="text-xs font-bold uppercase tracking-widest text-[#6B7280]">
                        {a.combined ? "Combined intervention" : `Intervention ${i + 1}`} —{" "}
                        <span className="font-mono normal-case">{a.commit_sha.slice(0, 10)}</span>
                        {a.stage_label && ` · ${a.stage_label}`}
                      </div>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${
                          success
                            ? "bg-emerald-50 text-emerald-700"
                            : insufficient
                              ? "bg-amber-50 text-amber-700"
                              : "bg-[#F7F8FA] text-[#6B7280]"
                        }`}
                      >
                        {verdictLabel(a.verdict)}
                      </span>
                    </div>
                    <div className="mb-2 grid grid-cols-2 gap-6 sm:grid-cols-3">
                      <div>
                        <div className="text-xs text-[#6B7280]">Before</div>
                        <div className="text-xl font-bold text-red-600">
                          {a.before_metric != null ? `${(a.before_metric * 100).toFixed(1)}%` : "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-[#6B7280]">After</div>
                        <div className="text-xl font-bold text-emerald-600">{(a.after_metric * 100).toFixed(1)}%</div>
                      </div>
                      {a.before_metric != null && (
                        <div>
                          <div className="text-xs text-[#6B7280]">Delta</div>
                          <div className="text-xl font-bold text-[#111827]">
                            {a.after_metric >= a.before_metric ? "+" : ""}
                            {((a.after_metric - a.before_metric) * 100).toFixed(1)}pt
                          </div>
                        </div>
                      )}
                    </div>
                    <p className="text-xs text-[#6B7280]">{verdictExplanation(a.verdict)}</p>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="mb-8 rounded-lg border border-[#E5E7EB] border-l-4 border-l-[#D1D5DB] bg-white p-6 shadow-sm">
              <p className="text-sm text-[#9CA3AF]">
                Waiting on the tenant's CI to report the controlled-intervention result (revert the suspect files,
                re-run the canary, and confirm whether accuracy recovers).
              </p>
            </div>
          )}
        </>
      )}

      {status === "incident" && whatChanged && interventions.length > 0 && session && id && (
        <>
          <SectionLabel>Recovery recommendation</SectionLabel>
          <RecoveryPanel
            userId={session.userId}
            repoId={parseInt(id, 10)}
            scanId={latest.id}
            repoFullName={repo?.repo_full_name ?? ""}
          />
        </>
      )}

      {status === "incident" && latestSummary && latestSummary.candidates.length > 0 && (
        <>
          <SectionLabel>Diagnostic ranking — {latestSummary.candidates.length} hypotheses</SectionLabel>
          <div className="mb-8 rounded-lg border border-[#E5E7EB] bg-white p-6 shadow-sm">
            <RankingTable candidates={latestSummary.candidates} theme="light" interventions={interventions} />
          </div>
        </>
      )}

      <SectionLabel>History</SectionLabel>
      <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-[#E5E7EB] bg-[#F7F8FA] text-xs text-[#6B7280]">
            <tr>
              <th className="px-4 py-2 font-medium">Time</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {scans.map((s) => (
              <tr key={s.id}>
                <td className="px-4 py-2 font-mono text-[#6B7280]">{new Date(s.created_at).toLocaleString()}</td>
                <td className="px-4 py-2">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-[#111827]">
                    <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[s.status] ?? STATUS_DOT.pending}`} />
                    {STATUS_LABEL[s.status] ?? s.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
