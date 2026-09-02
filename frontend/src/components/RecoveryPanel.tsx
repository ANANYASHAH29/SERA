import { useEffect, useState } from "react";
import { api } from "../api";
import type { RecoveryAction } from "../api";
import { Button, ErrorBanner } from "./StepCard";

/** Developer-approved "Recover Pipeline" workflow: shows the deterministic
 * recovery plan SERA computed from already-validated intervention
 * evidence, requires an explicit confirmation click before anything is
 * written to the repository, and reflects the real outcome once the
 * recovery commit's own CI run reports back (never a fabricated result).
 */
export function RecoveryPanel({
  userId,
  repoId,
  scanId,
  repoFullName,
}: {
  userId: number;
  repoId: number;
  scanId: number;
  repoFullName: string;
}) {
  const [plan, setPlan] = useState<RecoveryAction | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  function refresh() {
    api
      .getRecoveryPlan(userId, repoId, scanId)
      .then((p) => {
        setPlan(p);
        setLoadError(null);
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoaded(true));
  }

  useEffect(refresh, [userId, repoId, scanId]);

  async function confirmRecovery() {
    if (!plan) return;
    setConfirming(true);
    setConfirmError(null);
    try {
      const updated = await api.confirmRecovery(userId, repoId, scanId, plan.degraded_sha);
      setPlan(updated);
      setShowConfirm(false);
    } catch (e) {
      setConfirmError(e instanceof Error ? e.message : String(e));
    } finally {
      setConfirming(false);
    }
  }

  if (!loaded) return null;
  // No intervention evidence yet, or this incident already has no
  // recoverable basis -- say nothing rather than showing a broken panel.
  if (loadError) {
    return (
      <div className="mb-8 rounded-lg border border-dashed border-[#E5E7EB] bg-white p-4 text-xs text-[#9CA3AF]">
        Recovery not yet available: {loadError}
      </div>
    );
  }
  if (!plan) return null;

  const commitUrl = (sha: string) => `https://github.com/${repoFullName}/commit/${sha}`;
  const recoveryDelta =
    plan.before_metric != null && plan.after_metric != null ? (plan.after_metric - plan.before_metric) * 100 : null;

  return (
    <div className="mb-8 rounded-lg border border-[#E5E7EB] bg-white p-6 shadow-sm">
      {plan.status === "proposed" && (
        <>
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-[#6B7280]">
            Validated contributing changes
          </div>
          <ul className="mb-4 space-y-1">
            {plan.contributing.map((c) => (
              <li key={c.commit_sha} className="text-sm text-[#111827]">
                • <span className="font-mono">{c.commit_sha.slice(0, 10)}</span> — {c.stage_label ?? "—"}
              </li>
            ))}
          </ul>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 border-t border-[#E5E7EB] pt-4 text-sm">
            <div className="text-[#6B7280]">Recovery target</div>
            <div className="font-mono text-[#111827]">
              last known healthy — <a href={commitUrl(plan.healthy_sha)} target="_blank" rel="noreferrer" className="hover:underline">{plan.healthy_sha.slice(0, 10)}</a>
            </div>
            <div className="text-[#6B7280]">Current state</div>
            <div className="font-mono text-[#111827]">
              <a href={commitUrl(plan.degraded_sha)} target="_blank" rel="noreferrer" className="hover:underline">{plan.degraded_sha.slice(0, 10)}</a>
            </div>
            <div className="text-[#6B7280]">Files to restore</div>
            <div className="font-mono text-[#111827]">{plan.files.join(", ")}</div>
          </div>
          <div className="mt-4">
            <Button theme="light" onClick={() => setShowConfirm(true)}>
              Recover pipeline
            </Button>
          </div>
        </>
      )}

      {plan.status === "pending_ci" && (
        <>
          <div className="mb-1 text-base font-bold uppercase tracking-wide text-[#111827]">Recovery in progress</div>
          <p className="mb-2 text-sm text-[#374151]">
            Recovery commit{" "}
            <a href={commitUrl(plan.recovery_commit_sha ?? "")} target="_blank" rel="noreferrer" className="font-mono hover:underline">
              {plan.recovery_commit_sha?.slice(0, 10)}
            </a>{" "}
            was pushed. Waiting for the tenant's CI to report the resulting metrics.
          </p>
          <Button theme="light" variant="secondary" onClick={refresh}>
            Check now
          </Button>
        </>
      )}

      {plan.status === "recovered" && (
        <>
          <div className="mb-3 text-base font-bold uppercase tracking-wide text-emerald-700">✓ Pipeline recovered</div>
          <div className="mb-4 grid grid-cols-3 gap-6">
            <div>
              <div className="text-xs text-[#6B7280]">Before</div>
              <div className="text-2xl font-bold text-red-600">
                {plan.before_metric != null ? `${(plan.before_metric * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
            <div>
              <div className="text-xs text-[#6B7280]">After</div>
              <div className="text-2xl font-bold text-emerald-600">
                {plan.after_metric != null ? `${(plan.after_metric * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
            {recoveryDelta != null && (
              <div>
                <div className="text-xs text-[#6B7280]">Recovery</div>
                <div className="text-2xl font-bold text-[#111827]">+{recoveryDelta.toFixed(1)}pt</div>
              </div>
            )}
          </div>
          <a
            href={commitUrl(plan.recovery_commit_sha ?? "")}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-medium text-[#4F46E5] hover:underline"
          >
            View recovery commit ↗
          </a>
        </>
      )}

      {plan.status === "recovery_failed" && (
        <>
          <div className="mb-2 text-base font-bold uppercase tracking-wide text-red-700">✕ Recovery not verified</div>
          <p className="mb-2 text-sm text-[#374151]">
            The recovery commit was created, but the resulting pipeline did not return to the healthy baseline.
            Incident remains open.
          </p>
          <a
            href={commitUrl(plan.recovery_commit_sha ?? "")}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-medium text-[#4F46E5] hover:underline"
          >
            View CI run ↗
          </a>
        </>
      )}

      {plan.status === "aborted" && (
        <p className="text-sm text-[#9CA3AF]">
          Recovery was aborted (the repository changed since diagnosis, or nothing was left to restore). Re-run
          diagnosis and try again.
        </p>
      )}

      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
            <h3 className="mb-3 text-base font-bold uppercase tracking-wide text-[#111827]">Confirm pipeline recovery</h3>
            <p className="mb-4 text-sm text-[#374151]">
              This will create a new Git commit that restores the affected files to their last known healthy
              versions. CI will be re-run after recovery.
            </p>
            <div className="mb-4 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
              <div className="text-[#6B7280]">Repository</div>
              <div className="font-mono text-[#111827]">{repoFullName}</div>
              <div className="text-[#6B7280]">Current HEAD</div>
              <div className="font-mono text-[#111827]">{plan.degraded_sha.slice(0, 10)}</div>
              <div className="text-[#6B7280]">Healthy state</div>
              <div className="font-mono text-[#111827]">{plan.healthy_sha.slice(0, 10)}</div>
              <div className="text-[#6B7280]">Changes to restore</div>
              <div className="text-[#111827]">{plan.files.join(", ")}</div>
            </div>
            <ErrorBanner message={confirmError} theme="light" />
            <div className="mt-4 flex justify-end gap-2">
              <Button theme="light" variant="secondary" onClick={() => setShowConfirm(false)} disabled={confirming}>
                Cancel
              </Button>
              <Button theme="light" onClick={confirmRecovery} loading={confirming}>
                Confirm recovery
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
