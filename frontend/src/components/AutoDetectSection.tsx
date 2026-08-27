import { useEffect, useState } from "react";
import { api } from "../api";
import type { ScanSignalsOut } from "../api";
import { Button, ErrorBanner } from "./StepCard";

function SignalRow({ label, found, detail }: { label: string; found: boolean; detail?: string | null }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={found ? "text-emerald-600" : "text-slate-400"}>{found ? "✓" : "✗"}</span>
      <span className="text-slate-600">{label}</span>
      {detail && <span className="font-mono text-slate-400">({detail})</span>}
    </div>
  );
}

export function AutoDetectSection({ userId, repoId }: { userId: number; repoId: number }) {
  const [signals, setSignals] = useState<ScanSignalsOut | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [pasteValue, setPasteValue] = useState("");
  const [ingestResult, setIngestResult] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .detectSignals(userId, repoId)
      .then((s) => {
        setSignals(s);
        if (s.all_signals_found) {
          api.canaryDraft(userId, repoId).then((r) => setDraft(r.draft));
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [userId, repoId]);

  function copyDraft() {
    if (!draft) return;
    navigator.clipboard.writeText(draft);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function submitResult() {
    setSubmitting(true);
    setIngestResult(null);
    setError(null);
    try {
      const parsed = JSON.parse(pasteValue);
      const response = await api.ingestScanResult(userId, repoId, parsed);
      setIngestResult(
        `status: ${response.status}` +
          (response.metric_drop !== undefined ? ` (metric drop: ${response.metric_drop.toFixed(3)})` : "")
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  if (!signals) return <p className="text-xs text-slate-400">Scanning repo for a scikit-learn classifier…</p>;

  return (
    <section className="mb-6 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-2 text-sm font-semibold text-slate-700">
        Auto-detect evaluation script{" "}
        <span className="font-normal text-slate-400">(scikit-learn / tabular classifiers)</span>
      </h2>
      <p className="mb-3 text-xs text-slate-500">
        Static analysis only — SERA never downloads and executes a model file or runs your code to
        check this. It looks at filenames and reads .py source as text.
      </p>

      <div className="mb-3 space-y-1 rounded-md bg-slate-50 p-3">
        <SignalRow
          label="Model artifact (.pkl/.joblib)"
          found={signals.model_artifact.found}
          detail={signals.model_artifact.path}
        />
        <SignalRow
          label="scikit-learn import"
          found={signals.sklearn_import.found}
          detail={signals.sklearn_import.files[0]}
        />
        <SignalRow
          label="Held-out test set"
          found={signals.held_out_set_detected}
          detail={signals.held_out_csv.path ?? signals.train_test_split.file}
        />
      </div>

      <ErrorBanner message={error} theme="light" />

      {signals.all_signals_found && draft ? (
        <div className="mb-4">
          <p className="mb-2 text-xs text-emerald-700">
            Detected a scikit-learn classifier with a test split — here's a draft evaluation script.
            Review it, edit paths if needed, then run it yourself (locally or in CI — SERA never
            runs this for you) and paste its JSON output below.
          </p>
          <div className="relative">
            <pre className="max-h-64 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100">
              {draft}
            </pre>
            <button
              className="absolute right-2 top-2 rounded bg-slate-700 px-2 py-1 text-xs text-white hover:bg-slate-600"
              onClick={copyDraft}
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
        </div>
      ) : (
        <p className="mb-4 text-xs text-amber-700">
          Not all signals detected ({signals.missing_signals.join(", ")}) — write your own
          canary_eval.py by hand (see .sera.yml template above), run it, and paste its JSON output
          below. Nothing is blocked or silently failed here.
        </p>
      )}

      <div>
        <label className="mb-1 block text-xs font-medium text-slate-600">
          Paste your canary_eval.py's JSON output
        </label>
        <textarea
          className="mb-2 h-24 w-full rounded-md border border-slate-300 p-2 font-mono text-xs"
          placeholder='{"task_type": "classification", "primary_metric": 0.96, ...}'
          value={pasteValue}
          onChange={(e) => setPasteValue(e.target.value)}
        />
        <Button theme="light" loading={submitting} disabled={!pasteValue.trim()} onClick={submitResult}>
          Submit result
        </Button>
        {ingestResult && <span className="ml-3 text-xs text-emerald-700">{ingestResult}</span>}
      </div>
    </section>
  );
}
