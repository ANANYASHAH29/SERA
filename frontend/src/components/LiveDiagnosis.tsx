import { useState } from "react";
import { api } from "../api";
import type { IncidentSummary, RankingResponse, RunSummary, ValidationResponse } from "../api";
import { Button, ErrorBanner, StepCard } from "./StepCard";
import { RankingTable } from "./RankingTable";

const CONDITIONS = [
  { id: "F1", label: "F1 — resize dimension changed" },
  { id: "F2", label: "F2 — RGB/BGR channel swap" },
  { id: "F3", label: "F3 — normalization drift" },
  { id: "F4", label: "F4 — corrupted image leak" },
  { id: "F5", label: "F5 — wrong checkpoint loaded" },
  { id: "D1", label: "D1 — genuine covariate shift (no commit)" },
];

function RunMetricsCard({ label, run }: { label: string; run: RunSummary }) {
  return (
    <div className="rounded-md border border-slate-700 bg-slate-800/50 px-3 py-2 text-xs">
      <div className="mb-1 text-slate-400">{label}</div>
      <div className="grid grid-cols-3 gap-2 tabular-nums">
        <div>
          <div className="text-slate-500">accuracy</div>
          <div className="text-slate-100">{run.accuracy.toFixed(3)}</div>
        </div>
        <div>
          <div className="text-slate-500">confidence</div>
          <div className="text-slate-100">{run.mean_confidence.toFixed(3)}</div>
        </div>
        <div>
          <div className="text-slate-500">entropy</div>
          <div className="text-slate-100">{run.mean_entropy.toFixed(3)}</div>
        </div>
      </div>
    </div>
  );
}

export function LiveDiagnosis() {
  const [baseline, setBaseline] = useState<RunSummary | null>(null);
  const [condition, setCondition] = useState("F3");
  const [severity, setSeverity] = useState(0.9);
  const [regressed, setRegressed] = useState<RunSummary | null>(null);
  const [incident, setIncident] = useState<IncidentSummary | null>(null);
  const [historyMode, setHistoryMode] = useState<"synthetic" | "github">("synthetic");
  const [githubRepo, setGithubRepo] = useState("");
  const [githubSince, setGithubSince] = useState("");
  const [githubUntil, setGithubUntil] = useState("");
  const [historyAttached, setHistoryAttached] = useState(false);
  const [ranking, setRanking] = useState<RankingResponse | null>(null);
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run<T>(key: string, fn: () => Promise<T>, onDone: (r: T) => void) {
    setLoading(key);
    setError(null);
    try {
      const result = await fn();
      onDone(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(null);
    }
  }

  function reset() {
    setBaseline(null);
    setRegressed(null);
    setIncident(null);
    setHistoryAttached(false);
    setRanking(null);
    setValidation(null);
    setError(null);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          Walks through the same flow as the API: baseline run → inject a condition → detect →
          attach commit history → rank → validate the top candidate only.
        </p>
        <Button variant="secondary" onClick={reset}>
          Reset
        </Button>
      </div>

      <StepCard step={1} title="Healthy baseline run" done={!!baseline}>
        <div className="flex items-center gap-3">
          <Button
            loading={loading === "baseline"}
            onClick={() => run("baseline", () => api.createBaselineRun(0), setBaseline)}
          >
            Run baseline canary eval
          </Button>
          {baseline && <RunMetricsCard label={`run #${baseline.run_id} (baseline)`} run={baseline} />}
        </div>
      </StepCard>

      <StepCard step={2} title="Inject a regression condition" disabled={!baseline} done={!!regressed}>
        <div className="flex flex-wrap items-center gap-3">
          <select
            className="rounded-md border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm text-slate-100"
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
          >
            {CONDITIONS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-xs text-slate-400">
            severity
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.1}
              value={severity}
              onChange={(e) => setSeverity(parseFloat(e.target.value))}
            />
            <span className="tabular-nums">{severity.toFixed(1)}</span>
          </label>
          <Button
            loading={loading === "inject"}
            onClick={() =>
              run("inject", () => api.createInjectedRun(condition, severity, 0), setRegressed)
            }
          >
            Inject &amp; run
          </Button>
          {regressed && <RunMetricsCard label={`run #${regressed.run_id} (regressed)`} run={regressed} />}
        </div>
      </StepCard>

      <StepCard step={3} title="Detect regression" disabled={!regressed} done={!!incident}>
        <Button
          loading={loading === "detect"}
          onClick={() =>
            run(
              "detect",
              () => api.detectIncident(baseline!.run_id, regressed!.run_id),
              setIncident
            )
          }
        >
          Detect incident
        </Button>
        {incident && (
          <p className="mt-2 text-xs text-slate-400">
            incident #{incident.incident_id} — accuracy dropped{" "}
            <span className="text-red-400">{incident.accuracy_drop.toFixed(3)}</span>
          </p>
        )}
      </StepCard>

      <StepCard step={4} title="Attach commit history" disabled={!incident} done={historyAttached}>
        <div className="mb-2 flex gap-2 text-xs">
          <button
            className={`rounded px-2 py-1 ${historyMode === "synthetic" ? "bg-indigo-700 text-white" : "bg-slate-800 text-slate-400"}`}
            onClick={() => setHistoryMode("synthetic")}
          >
            Synthetic
          </button>
          <button
            className={`rounded px-2 py-1 ${historyMode === "github" ? "bg-indigo-700 text-white" : "bg-slate-800 text-slate-400"}`}
            onClick={() => setHistoryMode("github")}
          >
            Real GitHub repo
          </button>
        </div>
        {historyMode === "synthetic" ? (
          <Button
            loading={loading === "history"}
            onClick={() =>
              run(
                "history",
                () =>
                  api.attachSyntheticHistory(incident!.incident_id, {
                    num_harmless: 4,
                    guilty_category: condition === "D1" ? null : condition,
                    include_concurrent_unrelated: true,
                    window_hours: 72,
                    seed: 0,
                  }),
                () => setHistoryAttached(true)
              )
            }
          >
            Generate synthetic history (harmless commits + one matching {condition === "D1" ? "no" : condition} commit)
          </Button>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="w-48 rounded-md border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm"
              placeholder="owner/repo"
              value={githubRepo}
              onChange={(e) => setGithubRepo(e.target.value)}
            />
            <input
              className="rounded-md border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm"
              type="date"
              value={githubSince}
              onChange={(e) => setGithubSince(e.target.value)}
            />
            <input
              className="rounded-md border border-slate-600 bg-slate-800 px-2 py-1.5 text-sm"
              type="date"
              value={githubUntil}
              onChange={(e) => setGithubUntil(e.target.value)}
            />
            <Button
              loading={loading === "history"}
              disabled={!githubRepo || !githubSince || !githubUntil}
              onClick={() =>
                run(
                  "history",
                  () =>
                    api.attachGithubHistory(incident!.incident_id, {
                      repo_full_name: githubRepo,
                      since: `${githubSince}T00:00:00`,
                      until: `${githubUntil}T23:59:59`,
                    }),
                  () => setHistoryAttached(true)
                )
              }
            >
              Fetch real history
            </Button>
          </div>
        )}
      </StepCard>

      <StepCard step={5} title="Joint ranking" disabled={!historyAttached} done={!!ranking}>
        <Button
          loading={loading === "rank"}
          onClick={() => run("rank", () => api.rankIncident(incident!.incident_id), setRanking)}
        >
          Rank candidates
        </Button>
        {ranking && (
          <div className="mt-3">
            <RankingTable candidates={ranking.candidates} />
          </div>
        )}
      </StepCard>

      <StepCard step={6} title="Validate top candidate only" disabled={!ranking} done={!!validation}>
        <Button
          loading={loading === "validate"}
          onClick={() =>
            run("validate", () => api.validateIncident(incident!.incident_id), setValidation)
          }
        >
          Run isolated re-evaluation
        </Button>
        {validation && (
          <div
            className={`mt-3 rounded-md border px-3 py-2 text-xs ${
              validation.confirmed
                ? "border-emerald-700 bg-emerald-950/30 text-emerald-300"
                : "border-red-800 bg-red-950/30 text-red-300"
            }`}
          >
            {validation.confirmed ? "CONFIRMED" : "NOT CONFIRMED"} —{" "}
            {validation.kind === "drift" ? "genuine drift" : `commit ${validation.candidate_id.slice(0, 10)}`}{" "}
            · before {validation.before_accuracy.toFixed(3)} → after{" "}
            {validation.after_accuracy.toFixed(3)} (baseline {validation.baseline_accuracy.toFixed(3)})
          </div>
        )}
      </StepCard>

      <ErrorBanner message={error} />
    </div>
  );
}
