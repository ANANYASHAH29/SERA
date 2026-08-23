import { useEffect, useState } from "react";
import { api, RESULTS_STATIC_BASE } from "../api";
import type { ExperimentsSummary } from "../api";
import { ErrorBanner } from "./StepCard";

function pct(x: number) {
  return `${(x * 100).toFixed(1)}%`;
}

export function ExperimentResults() {
  const [data, setData] = useState<ExperimentsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedMethod, setSelectedMethod] = useState<string>("sera");

  useEffect(() => {
    api
      .experimentsSummary()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <div className="text-sm text-slate-400">
        <ErrorBanner message={error} />
        <p className="mt-2">
          Run <code className="text-slate-300">experiments/run_trials.py</code>,{" "}
          <code className="text-slate-300">build_confusion_matrix.py</code>, and{" "}
          <code className="text-slate-300">cost_comparison.py</code> first.
        </p>
      </div>
    );
  }

  if (!data) return <p className="text-sm text-slate-500">Loading…</p>;

  const bestTop1 = Math.max(...data.accuracy_summary.map((r) => r.top1_accuracy));

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-200">
          Top-1 / top-2 accuracy across seeds (95% CI)
        </h3>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-slate-500">
              <th className="py-1 pr-4 font-medium">method</th>
              <th className="py-1 pr-4 font-medium">n</th>
              <th className="py-1 pr-4 font-medium">top-1</th>
              <th className="py-1 pr-4 font-medium">top-2</th>
            </tr>
          </thead>
          <tbody>
            {data.accuracy_summary.map((row) => (
              <tr key={row.method} className="border-t border-slate-800">
                <td className="py-1.5 pr-4 font-mono text-slate-200">
                  {row.method}
                  {row.top1_accuracy === bestTop1 && (
                    <span className="ml-2 rounded bg-emerald-800/50 px-1.5 py-0.5 text-emerald-300">
                      best
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-4 text-slate-400">{row.n_trials}</td>
                <td className="py-1.5 pr-4 tabular-nums text-slate-100">
                  {pct(row.top1_accuracy)}{" "}
                  <span className="text-slate-500">
                    [{pct(row.top1_ci_low)}, {pct(row.top1_ci_high)}]
                  </span>
                </td>
                <td className="py-1.5 pr-4 tabular-nums text-slate-100">
                  {pct(row.top2_accuracy)}{" "}
                  <span className="text-slate-500">
                    [{pct(row.top2_ci_low)}, {pct(row.top2_ci_high)}]
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-200">
          Cost comparison — accuracy vs. expensive re-evaluations
        </h3>
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-slate-500">
              <th className="py-1 pr-4 font-medium">method</th>
              <th className="py-1 pr-4 font-medium">top-1 acc</th>
              <th className="py-1 pr-4 font-medium">mean re-evals</th>
              <th className="py-1 pr-4 font-medium">max re-evals</th>
            </tr>
          </thead>
          <tbody>
            {data.cost_comparison.map((row) => (
              <tr key={row.method} className="border-t border-slate-800">
                <td className="py-1.5 pr-4 font-mono text-slate-200">{row.method}</td>
                <td className="py-1.5 pr-4 tabular-nums text-slate-100">{pct(row.top1_accuracy)}</td>
                <td className="py-1.5 pr-4 tabular-nums text-slate-100">
                  {row.mean_reevaluations.toFixed(2)}
                </td>
                <td className="py-1.5 pr-4 tabular-nums text-slate-100">{row.max_reevaluations}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-slate-500">
          SERA and the shape/naive baselines validate exactly one candidate per incident.
          full_bisection pays for O(log N) re-evaluations per incident to reach its answer.
        </p>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-200">Confusion matrix</h3>
        <div className="mb-3 flex gap-2 text-xs">
          {Object.keys(data.confusion_matrices).map((method) => (
            <button
              key={method}
              className={`rounded px-2 py-1 font-mono ${
                selectedMethod === method
                  ? "bg-indigo-700 text-white"
                  : "bg-slate-800 text-slate-400"
              }`}
              onClick={() => setSelectedMethod(method)}
            >
              {method}
            </button>
          ))}
        </div>
        <img
          src={`${RESULTS_STATIC_BASE}/confusion_matrix_${selectedMethod}.png`}
          alt={`confusion matrix for ${selectedMethod}`}
          className="max-w-xl rounded-md border border-slate-800"
        />
      </section>
    </div>
  );
}
