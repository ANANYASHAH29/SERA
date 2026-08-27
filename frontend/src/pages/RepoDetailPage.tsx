import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { ConnectedRepoOut, ScanResultOut } from "../api";
import { useSession } from "../session";
import { RankingTable } from "../components/RankingTable";
import { AccuracyChart } from "../components/AccuracyChart";
import { ErrorBanner } from "../components/StepCard";
import { describeLikelyCause, parseScanSummary, timeAgo } from "../scanSummary";

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
          <h1 className="mt-1 font-mono text-lg font-semibold text-slate-800">
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
            <h1 className="font-mono text-lg font-semibold text-slate-800">
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

      <div className="mb-6 grid grid-cols-2 gap-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:grid-cols-4">
        <MetricCard label={latestSummary?.primaryMetricName ?? "accuracy"}>
          <div className={`text-2xl font-semibold ${status === "incident" ? "text-red-600" : "text-slate-800"}`}>
            {latestSummary ? `${(latestSummary.currentMetric * 100).toFixed(1)}%` : "—"}
          </div>
          {status === "incident" && latestSummary && (
            <div className="text-xs text-red-500">↓ {(latestSummary.metricDrop * 100).toFixed(1)}pt vs baseline</div>
          )}
        </MetricCard>

        <MetricCard label="mean confidence">
          <div className="text-2xl font-semibold text-slate-800">
            {latestSummary?.meanConfidence != null ? latestSummary.meanConfidence.toFixed(2) : "—"}
          </div>
          {confidentlyWrong && <div className="text-xs text-amber-600">confidently wrong</div>}
        </MetricCard>

        <MetricCard label="last scan">
          <div className="text-2xl font-semibold text-slate-800">{timeAgo(latest.created_at)}</div>
          <div className="text-xs text-slate-400">manual / paste-in</div>
        </MetricCard>

        <MetricCard label="suspect commit">
          {suspectCommit && suspectCommit.kind === "commit" ? (
            <>
              <div className="font-mono text-2xl font-semibold text-slate-800">
                {suspectCommit.commit_sha?.slice(0, 7)}
              </div>
              <div className="text-xs text-slate-400">{suspectCommit.hypothesized_category}</div>
            </>
          ) : (
            <div className="text-2xl font-semibold text-slate-400">—</div>
          )}
        </MetricCard>
      </div>

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">
          {latestSummary?.primaryMetricName ?? "accuracy"} over time — last {Math.min(chartPoints.length, 10)} scans
        </h2>
        <AccuracyChart points={chartPoints} />
      </div>

      {likelyCause && (
        <div className="mb-6 rounded-lg border-l-4 border-red-400 bg-red-50 p-4">
          <h2 className="mb-1 text-sm font-semibold text-red-900">{likelyCause.title}</h2>
          <p className="text-sm text-red-700">{likelyCause.body}</p>
        </div>
      )}

      {status === "incident" && latestSummary && latestSummary.candidates.length > 0 && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
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
