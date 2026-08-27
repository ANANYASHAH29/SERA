import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { ConnectedRepoOut, HealthStatus } from "../api";
import { useSession } from "../session";
import { Button, ErrorBanner } from "../components/StepCard";

const STATUS_STYLE: Record<HealthStatus, string> = {
  healthy: "bg-emerald-100 text-emerald-700 border-emerald-300",
  incident: "bg-red-100 text-red-700 border-red-300",
  pending: "bg-amber-100 text-amber-700 border-amber-300",
  never_scanned: "bg-slate-100 text-slate-500 border-slate-300",
};

const STATUS_LABEL: Record<HealthStatus, string> = {
  healthy: "Healthy",
  incident: "Incident",
  pending: "Scan pending",
  never_scanned: "Not yet scanned",
};

function StatusBadge({ status }: { status: HealthStatus }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

function RepoConnector({ userId, installationId, onConnected }: { userId: number; installationId: number; onConnected: () => void }) {
  const [available, setAvailable] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);

  useEffect(() => {
    api
      .availableRepos(installationId)
      .then(setAvailable)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [installationId]);

  async function connect(repoFullName: string) {
    setConnecting(repoFullName);
    try {
      await api.connectRepo(userId, repoFullName);
      onConnected();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setConnecting(null);
    }
  }

  if (error) return <ErrorBanner message={error} theme="light" />;
  if (available === null) return <p className="text-xs text-slate-400">Loading repos granted to this installation…</p>;
  if (available.length === 0) return <p className="text-xs text-slate-400">No repos available to connect.</p>;

  return (
    <ul className="divide-y divide-slate-100">
      {available.map((name) => (
        <li key={name} className="flex items-center justify-between py-2">
          <span className="font-mono text-sm text-slate-700">{name}</span>
          <Button
            theme="light"
            variant="secondary"
            loading={connecting === name}
            onClick={() => connect(name)}
          >
            Connect
          </Button>
        </li>
      ))}
    </ul>
  );
}

export function RepoOverviewPage() {
  const { session, logOut } = useSession();
  const [repos, setRepos] = useState<ConnectedRepoOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showConnector, setShowConnector] = useState(false);

  function refresh() {
    if (!session) return;
    api
      .listConnectedRepos(session.userId)
      .then(setRepos)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(refresh, [session]);

  if (!session) {
    return (
      <div className="mx-auto mt-16 max-w-md text-center text-sm text-slate-500">
        <p>Not connected yet.</p>
        <Link className="mt-2 inline-block text-indigo-600 underline" to="/connect">
          Go to the connect flow
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">Your repos</h1>
          <p className="text-xs text-slate-400">signed in as {session.githubUsername}</p>
        </div>
        <div className="flex gap-2">
          {session.installationId && (
            <Button theme="light" variant="secondary" onClick={() => setShowConnector((v) => !v)}>
              {showConnector ? "Hide" : "Connect another repo"}
            </Button>
          )}
          <Button theme="light" variant="secondary" onClick={logOut}>
            Log out
          </Button>
        </div>
      </div>

      <ErrorBanner message={error} theme="light" />

      {showConnector && session.installationId && (
        <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <RepoConnector
            userId={session.userId}
            installationId={session.installationId}
            onConnected={() => {
              refresh();
              setShowConnector(false);
            }}
          />
        </div>
      )}

      {repos === null ? (
        <p className="text-sm text-slate-400">Loading…</p>
      ) : repos.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-400">
          No repos connected yet.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-2 font-medium">Repo</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Last scan</th>
                <th className="px-4 py-2 font-medium">Incidents</th>
                <th className="px-4 py-2 font-medium">.sera.yml</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {repos.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2">
                    <Link to={`/repos/${r.id}`} className="font-mono text-indigo-600 hover:underline">
                      {r.repo_full_name}
                    </Link>
                  </td>
                  <td className="px-4 py-2">
                    <StatusBadge status={r.health_status} />
                  </td>
                  <td className="px-4 py-2 text-slate-500">
                    {r.last_scan_at ? new Date(r.last_scan_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2 text-slate-700">{r.incident_count}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs ${
                        r.sera_yml_status === "present"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-amber-50 text-amber-700"
                      }`}
                    >
                      {r.sera_yml_status}
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
