import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useSession } from "../session";

// GitHub redirects here after a successful App install, with
// ?installation_id=...&setup_action=install in the query string. The
// installation webhook (routes_webhook.py) may not have been processed
// yet by the time this page loads, so we poll briefly rather than
// failing on the first miss.
const MAX_ATTEMPTS = 8;
const POLL_INTERVAL_MS = 1500;

export function ConnectCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { setSession } = useSession();
  const [status, setStatus] = useState("Finishing setup…");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const installationId = parseInt(params.get("installation_id") ?? "", 10);
    if (!installationId) {
      setStatus("No installation_id in the redirect — something went wrong.");
      setFailed(true);
      return;
    }

    let attempt = 0;
    let cancelled = false;

    async function poll() {
      attempt += 1;
      try {
        const { user_id, github_username } = await api.userByInstallation(installationId);
        if (cancelled) return;
        setSession({ userId: user_id, githubUsername: github_username, installationId });
        navigate("/");
      } catch {
        if (cancelled) return;
        if (attempt >= MAX_ATTEMPTS) {
          setStatus(
            "Still waiting on GitHub's installation webhook — this can take a few extra " +
              "seconds. Refresh this page to try again."
          );
          setFailed(true);
          return;
        }
        setStatus(`Waiting for installation to finish setting up… (attempt ${attempt}/${MAX_ATTEMPTS})`);
        setTimeout(poll, POLL_INTERVAL_MS);
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, [params, navigate, setSession]);

  return (
    <div className="mx-auto mt-24 max-w-md text-center text-sm text-slate-500">
      <p>{status}</p>
      {failed && (
        <button
          className="mt-4 rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white"
          onClick={() => window.location.reload()}
        >
          Retry
        </button>
      )}
    </div>
  );
}
