import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { ConnectedRepoOut, RankingResponse, ScanResultOut } from "../api";
import { useSession } from "../session";
import { RankingTable } from "../components/RankingTable";
import { Button, ErrorBanner } from "../components/StepCard";

const SCAN_OPTIONS = [
  { value: "", label: "Healthy (no injected condition)" },
  { value: "F1", label: "F1 — resize dimension changed" },
  { value: "F2", label: "F2 — RGB/BGR channel swap" },
  { value: "F3", label: "F3 — normalization drift" },
  { value: "F4", label: "F4 — corrupted image leak" },
  { value: "F5", label: "F5 — wrong checkpoint loaded" },
  { value: "D1", label: "D1 — genuine covariate shift (no commit)" },
];

const STATUS_STYLE: Record<string, string> = {
  healthy: "bg-emerald-100 text-emerald-700 border-emerald-300",
  incident: "bg-red-100 text-red-700 border-red-300",
  pending: "bg-amber-100 text-amber-700 border-amber-300",
  error: "bg-slate-100 text-slate-500 border-slate-300",
};

function tryParseRanking(summaryJson: string | null): RankingResponse["candidates"] | null {
  if (!summaryJson) return null;
  try {
    const parsed = JSON.parse(summaryJson);
    return Array.isArray(parsed?.candidates) ? parsed.candidates : null;
  } catch {
    return null;
  }
}

export function RepoDetailPage() {
  const { id } = useParams();
  const { session } = useSession();
  const [repo, setRepo] = useState<ConnectedRepoOut | null>(null);
  const [scans, setScans] = useState<ScanResultOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanCondition, setScanCondition] = useState("");
  const [scanning, setScanning] = useState(false);

  function refresh() {
    if (!session || !id) return;
    const repoId = parseInt(id, 10);
    api
      .listConnectedRepos(session.userId)
      .then((repos) => setRepo(repos.find((r) => r.id === repoId) ?? null));
    api
      .repoScans(session.userId, repoId)
      .then(setScans)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(refresh, [session, id]);

  async function triggerScan() {
    if (!session || !id) return;
    setScanning(true);
    setError(null);
    try {
      await api.runDemoScan(session.userId, parseInt(id, 10), scanCondition || null);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setScanning(false);
    }
  }

  if (!session) {
    return <p className="text-sm text-slate-500">Not connected — go to the connect flow first.</p>;
  }
  if (error) return <ErrorBanner message={error} theme="light" />;
  if (!scans) return <p className="text-sm text-slate-400">Loading…</p>;

  const latestIncidentScan = scans.find((s) => s.status === "incident");
  const latestCandidates = latestIncidentScan ? tryParseRanking(latestIncidentScan.summary_json) : null;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Link to="/" className="text-xs text-indigo-600 hover:underline">
            ← all repos
          </Link>
          <h1 className="mt-1 font-mono text-lg font-semibold text-slate-800">
            {repo?.repo_full_name ?? `repo #${id}`}
          </h1>
        </div>
        {id && (
          <Link to={`/repos/${id}/settings`} className="text-sm text-indigo-600 hover:underline">
            Settings
          </Link>
        )}
      </div>

      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-1 text-sm font-semibold text-slate-700">Run a scan</h2>
        <p className="mb-3 text-xs text-slate-500">
          Runs SERA's real diagnostic engine (real ResNet-18 inference, real ranking) against the
          reference CIFAR-10 canary set — not this repo's own code, since executing an arbitrary
          connected repo's canary script safely per-scan needs a sandboxed worker queue this build
          doesn't include yet (see README "Known limitations"). Pick a condition to simulate a
          regression, or "Healthy" to simulate a clean scan.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-700"
            value={scanCondition}
            onChange={(e) => setScanCondition(e.target.value)}
          >
            {SCAN_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <Button theme="light" loading={scanning} onClick={triggerScan}>
            Run scan
          </Button>
        </div>
      </div>

      {latestIncidentScan ? (
        <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4">
          <h2 className="mb-1 text-sm font-semibold text-red-800">Most recent incident</h2>
          <p className="mb-3 text-xs text-red-600">
            detected {new Date(latestIncidentScan.created_at).toLocaleString()}
          </p>
          {latestCandidates ? (
            <div className="rounded-md bg-white p-3">
              <RankingTable candidates={latestCandidates} theme="light" />
            </div>
          ) : (
            <p className="text-xs text-red-500">
              (no structured ranking stored for this scan — this repo's scans were likely created
              before the ranking-snapshot format existed)
            </p>
          )}
        </div>
      ) : (
        <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
          No incidents recorded — every scan so far has come back healthy.
        </div>
      )}

      <h2 className="mb-2 text-sm font-semibold text-slate-700">Scan history</h2>
      {scans.length === 0 ? (
        <p className="text-sm text-slate-400">
          No scans yet. Scans run on a schedule (see the "SERA scheduled canary" Action) or when
          triggered manually — this repo hasn't had one yet.
        </p>
      ) : (
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
                  <td className="px-4 py-2 text-slate-500">
                    {new Date(s.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                        STATUS_STYLE[s.status] ?? STATUS_STYLE.error
                      }`}
                    >
                      {s.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
