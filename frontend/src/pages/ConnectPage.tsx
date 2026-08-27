import { useState } from "react";
import { api } from "../api";
import { useSession } from "../session";
import { Button, ErrorBanner } from "../components/StepCard";

export function ConnectPage() {
  const { setSession } = useSession();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [devUserId, setDevUserId] = useState("");

  async function handleInstall() {
    setLoading(true);
    setError(null);
    try {
      const { install_url } = await api.installUrl();
      window.location.href = install_url;
    } catch (e) {
      setError(
        e instanceof Error
          ? `${e.message} — the GitHub App hasn't been registered yet (see README "Setting up the GitHub App").`
          : String(e)
      );
      setLoading(false);
    }
  }

  async function handleDevLogin() {
    const userId = parseInt(devUserId, 10);
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const repos = await api.listConnectedRepos(userId);
      setSession({ userId, githubUsername: `user#${userId}`, installationId: null });
      void repos; // just confirming the id is valid before committing to it
      window.location.href = "/";
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <h1 className="text-2xl font-semibold text-slate-800">Connect your repo to SERA</h1>
      <p className="mt-2 text-sm text-slate-500">
        SERA scans your CV pipeline for accuracy regressions and tells you whether a commit or
        genuine data drift caused them — without re-evaluating every candidate commit.
      </p>

      <div className="mt-8">
        <Button theme="light" onClick={handleInstall} loading={loading}>
          Install SERA on GitHub
        </Button>
        <p className="mt-2 text-xs text-slate-400">
          Opens GitHub's install flow — you choose which repos to grant access to.
        </p>
      </div>

      <ErrorBanner message={error} theme="light" />

      <details className="mt-10 rounded-lg border border-slate-200 bg-slate-50 p-3 text-left text-xs text-slate-500">
        <summary className="cursor-pointer font-medium text-slate-600">
          Developer/testing shortcut (no live GitHub App yet)
        </summary>
        <p className="mt-2">
          If you already have a user id from a webhook-seeded test user, enter it here to skip
          the GitHub redirect entirely.
        </p>
        <div className="mt-2 flex gap-2">
          <input
            className="w-24 rounded border border-slate-300 px-2 py-1"
            placeholder="user id"
            value={devUserId}
            onChange={(e) => setDevUserId(e.target.value)}
          />
          <Button theme="light" variant="secondary" onClick={handleDevLogin}>
            Use this id
          </Button>
        </div>
      </details>
    </div>
  );
}
