import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { ConnectedRepoOut, ScanResultOut } from "../api";
import { useSession } from "../session";
import { RankingTable } from "../components/RankingTable";
import { AccuracyChart } from "../components/AccuracyChart";
import { ErrorBanner } from "../components/StepCard";
import { describeLikelyCause, describeWhatChanged, parseScanSummary, parseValidation, sourceLabel, timeAgo } from "../scanSummary";

const STATUS_PILL: Record<string, string> = {
  healthy: "bg-emerald-100 text-emerald-700",
  incident: "bg-red-100 text-red-700",
  pending: "bg-amber-100 text-amber-700",
  never_scanned: "bg-slate-100 text-slate-500",
};

const STATUS_LABEL: Record<string, string> = {
  healthy: "healthy",
  incident: "degraded",
  pending: "pending",
  never_scanned: "not yet scanned",
};

function MetricCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1">{children}</div>
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
    return <p className="text-sm text-slate-500">Not connected — go to the connect flow first.</p>;
  }
  if (error) return <ErrorBanner message={error} theme="light" />;
  if (!scans) return <p className="text-sm text-slate-400">Loading…</p>;

  if (scans.length === 0) {
    return (
      <div>
        <div className="mb-4">
          <Link to="/" className="text-xs text-indigo-600 hover:underline">
            ← all repos
          </Link>
          <h1 className="mt-1 font-mono text-xl font-semibold text-slate-800">
            {repo?.repo_full_name ?? `repo #${id}`}
          </h1>
        </div>
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
          No scans yet. Go to <Link to={`/repos/${id}/settings`} className="text-indigo-600 hover:underline">Settings</Link> to
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
  const likelyCause = status === "incident" && latestSummary ? describeLikelyCause(latestSummary) : null;
  const whatChanged = status === "incident" && latestSummary ? describeWhatChanged(latestSummary) : null;
  const validation = status === "incident" ? parseValidation(latest.validation_json) : null;
  // Only meaningful as an explanation for a real regression -- a healthy
  // scan can have a nonzero confident_but_wrong signal from noise alone
  // (a few samples flipped without moving overall accuracy past the
  // regression threshold), and surfacing the annotation there would wrongly
  // imply something's currently wrong when the status pill says otherwise.
  const confidentlyWrong = status === "incident" && (latestSummary?.observedShape?.confident_but_wrong ?? 0) > 0.5;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Link to="/" className="text-xs text-indigo-600 hover:underline">
            ← all repos
          </Link>
          <div className="mt-1 flex items-center gap-2">
            <h1 className="font-mono text-xl font-semibold text-slate-800">
              {repo?.repo_full_name ?? `repo #${id}`}
            </h1>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_PILL[status] ?? STATUS_PILL.pending}`}>
              {STATUS_LABEL[status] ?? status}
            </span>
          </div>
        </div>
        <Link to={`/repos/${id}/settings`} className="text-sm text-indigo-600 hover:underline">
          Settings
        </Link>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm sm:grid-cols-4">
        <MetricCard label={latestSummary?.primaryMetricName ?? "accuracy"}>
          <div className={`text-3xl font-semibold ${status === "incident" ? "text-red-600" : "text-slate-800"}`}>
            {latestSummary ? `${(latestSummary.currentMetric * 100).toFixed(1)}%` : "—"}
          </div>
          {status === "incident" && latestSummary && (
            <div className="text-xs text-red-500">↓ {(latestSummary.metricDrop * 100).toFixed(1)}pt vs baseline</div>
          )}
        </MetricCard>

        <MetricCard label="mean confidence">
          <div className="text-3xl font-semibold text-slate-800">
            {latestSummary?.meanConfidence != null ? latestSummary.meanConfidence.toFixed(2) : "—"}
          </div>
          {confidentlyWrong && <div className="text-xs text-amber-600">confidently wrong</div>}
        </MetricCard>

        <MetricCard label="last scan">
          <div className="text-3xl font-semibold text-slate-800">{timeAgo(latest.created_at)}</div>
          <div className="text-xs text-slate-400">{sourceLabel(latestSummary?.source ?? "manual")}</div>
        </MetricCard>

        <MetricCard label="suspect commit">
          {suspectCommit && suspectCommit.kind === "commit" ? (
            <>
              <div className="font-mono text-3xl font-semibold text-slate-800">
                {suspectCommit.commit_sha?.slice(0, 7)}
              </div>
              <div className="text-xs text-slate-400">
                {suspectCommit.stage_label ?? suspectCommit.hypothesized_category}
                {suspectCommit.commit_author && ` · ${suspectCommit.commit_author}`}
              </div>
            </>
          ) : (
            <div className="text-3xl font-semibold text-slate-400">—</div>
          )}
        </MetricCard>
      </div>

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">
          {latestSummary?.primaryMetricName ?? "accuracy"} over time — last {Math.min(chartPoints.length, 10)} scans
        </h2>
        <AccuracyChart points={chartPoints} />
      </div>

      {likelyCause && (
        <div className="mb-6 rounded-lg border-l-4 border-red-400 bg-red-50 p-6">
          <h2 className="mb-1 text-sm font-semibold text-red-900">{likelyCause.title}</h2>
          <p className="text-sm text-red-700">{likelyCause.body}</p>
        </div>
      )}

      {whatChanged && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">What changed</h2>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <div className="text-slate-500">Commit</div>
            <div className="font-mono text-slate-800">
              {whatChanged.commitSha.slice(0, 10)}
              {whatChanged.commitMessage && (
                <span className="ml-2 font-sans text-slate-500">— {whatChanged.commitMessage}</span>
              )}
            </div>
            <div className="text-slate-500">Author</div>
            <div className="text-slate-800">{whatChanged.commitAuthor ?? "—"}</div>
            <div className="text-slate-500">Pipeline stage</div>
            <div className="text-slate-800">{whatChanged.stageLabel ?? "—"}</div>
          </div>

          <div className="mt-3 text-sm">
            <div className="mb-1 text-slate-500">Modified</div>
            <ul className="space-y-2">
              {whatChanged.files.map((f) => (
                <li key={f.path}>
                  <div className="font-mono text-slate-800">• {f.path}</div>
                  {f.patch ? (
                    <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-xs text-slate-700">
                      {f.patch}
                    </pre>
                  ) : (
                    <div className="ml-3 text-xs text-slate-400">binary artifact — no text diff available</div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {status === "incident" && whatChanged && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Validation</h2>
          {validation ? (
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
              <div className="text-slate-500">Intervention</div>
              <div className="text-slate-800">
                Restore {validation.files_reverted.join(", ")} to its state before commit{" "}
                <span className="font-mono">{whatChanged.commitSha.slice(0, 10)}</span>
              </div>
              <div className="text-slate-500">Before intervention</div>
              <div className="text-slate-800">
                {validation.before_metric != null ? `${(validation.before_metric * 100).toFixed(1)}%` : "—"}
              </div>
              <div className="text-slate-500">After intervention</div>
              <div className="text-slate-800">{(validation.after_metric * 100).toFixed(1)}%</div>
              <div className="col-span-2 mt-1">
                {validation.recovered ? (
                  <span className="font-medium text-emerald-600">
                    ✓ Degradation recovered — cause validated
                  </span>
                ) : (
                  <span className="font-medium text-amber-600">
                    ✗ Accuracy did not recover — this commit alone may not fully explain the regression
                  </span>
                )}
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-400">
              Waiting on the tenant's CI to report the controlled-intervention result (revert the suspect
              files, re-run the canary, and confirm whether accuracy recovers).
            </p>
          )}
        </div>
      )}

      {status === "incident" && whatChanged && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Recovery &amp; feedback</h2>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <div className="text-slate-500">Recommended action</div>
            <div className="text-slate-800">
              {validation?.recovered
                ? `Revert ${validation.files_reverted.join(", ")} in commit ${whatChanged.commitSha.slice(0, 10)}`
                : validation
                  ? "Reverting this commit alone didn't recover accuracy — keep investigating the next-ranked candidate"
                  : `Review ${whatChanged.files.map((f) => f.path).join(", ")} in commit ${whatChanged.commitSha.slice(0, 10)}`}
            </div>
            <div className="text-slate-500">Developer</div>
            <div className="text-slate-800">Review &amp; apply</div>
          </div>
          <div className="mt-2 text-xs text-emerald-600">Incident stored ✓ (scan #{latest.id})</div>
        </div>
      )}

      {status === "incident" && latestSummary && latestSummary.candidates.length > 0 && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Full ranking</h2>
          <RankingTable candidates={latestSummary.candidates} theme="light" />
        </div>
      )}

      <h2 className="mb-2 text-sm font-semibold text-slate-700">Scan history</h2>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Time</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {scans.map((s) => (
              <tr key={s.id}>
                <td className="px-4 py-2 text-slate-500">{new Date(s.created_at).toLocaleString()}</td>
                <td className="px-4 py-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_PILL[s.status] ?? STATUS_PILL.pending}`}>
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
