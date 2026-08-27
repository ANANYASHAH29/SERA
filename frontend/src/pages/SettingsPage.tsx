import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { ConnectedRepoOut } from "../api";
import { useSession } from "../session";
import { Button, ErrorBanner } from "../components/StepCard";

export function SettingsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { session } = useSession();
  const [repo, setRepo] = useState<ConnectedRepoOut | null>(null);
  const [template, setTemplate] = useState<string | null>(null);
  const [badge, setBadge] = useState<{ markdown: string; badge_url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!session || !id) return;
    const repoId = parseInt(id, 10);
    api.listConnectedRepos(session.userId).then((repos) => setRepo(repos.find((r) => r.id === repoId) ?? null));
    api
      .seraYmlTemplate(session.userId, repoId)
      .then((r) => setTemplate(r.template))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    api
      .badgeMarkdown(session.userId, repoId)
      .then(setBadge)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [session, id]);

  async function handleDisconnect() {
    if (!session || !id) return;
    if (!window.confirm(`Disconnect ${repo?.repo_full_name ?? "this repo"}? Scan history is kept.`)) return;
    await api.disconnectRepo(session.userId, parseInt(id, 10));
    navigate("/");
  }

  function copyBadge() {
    if (!badge) return;
    navigator.clipboard.writeText(badge.markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  if (!session) return <p className="text-sm text-slate-500">Not connected.</p>;

  return (
    <div className="mx-auto max-w-2xl">
      <Link to={`/repos/${id}`} className="text-xs text-indigo-600 hover:underline">
        ← back to {repo?.repo_full_name ?? "repo"}
      </Link>
      <h1 className="mt-1 mb-6 text-lg font-semibold text-slate-800">Settings</h1>

      <ErrorBanner message={error} theme="light" />

      <section className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-2 text-sm font-semibold text-slate-700">.sera.yml</h2>
        <p className="mb-2 text-xs text-slate-500">
          Current status:{" "}
          <span
            className={
              repo?.sera_yml_status === "present" ? "text-emerald-600" : "text-amber-600"
            }
          >
            {repo?.sera_yml_status ?? "…"}
          </span>
          {repo?.sera_yml_status !== "present" && (
            <> — drop this starter template in your repo's root and edit the paths for your pipeline.</>
          )}
        </p>
        {template && (
          <pre className="max-h-72 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100">
            {template}
          </pre>
        )}
      </section>

      <section className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-2 text-sm font-semibold text-slate-700">README badge</h2>
        {badge && (
          <div className="flex items-center gap-2">
            <img src={badge.badge_url} alt="SERA status badge" />
            <code className="flex-1 rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">
              {badge.markdown}
            </code>
            <Button theme="light" variant="secondary" onClick={copyBadge}>
              {copied ? "Copied!" : "Copy"}
            </Button>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-red-200 bg-red-50 p-4">
        <h2 className="mb-2 text-sm font-semibold text-red-800">Disconnect repo</h2>
        <p className="mb-3 text-xs text-red-600">
          Stops future scans. Past scan and incident history is kept, not deleted.
        </p>
        <Button theme="light" variant="secondary" onClick={handleDisconnect}>
          Disconnect
        </Button>
      </section>
    </div>
  );
}
