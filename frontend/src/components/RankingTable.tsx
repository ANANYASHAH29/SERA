import type { RankedCandidateOut } from "../api";

function ScoreBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full ${color}`} style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className="w-10 text-right text-xs tabular-nums text-slate-400">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

export function RankingTable({ candidates }: { candidates: RankedCandidateOut[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="text-slate-500">
            <th className="py-1 pr-3 font-medium">#</th>
            <th className="py-1 pr-3 font-medium">Candidate</th>
            <th className="py-1 pr-3 font-medium">Category</th>
            <th className="py-1 pr-3 font-medium">Provenance</th>
            <th className="py-1 pr-3 font-medium">Shape match</th>
            <th className="py-1 pr-3 font-medium">Combined</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => {
            const isTop = c.rank === 0;
            const isDrift = c.kind === "drift";
            return (
              <tr
                key={c.candidate_id}
                className={`border-t border-slate-800 ${isTop ? "bg-indigo-950/30" : ""}`}
              >
                <td className="py-1.5 pr-3 text-slate-500">{c.rank + 1}</td>
                <td className="py-1.5 pr-3 font-mono">
                  {isDrift ? (
                    <span className="rounded bg-amber-900/40 px-1.5 py-0.5 text-amber-300">
                      NO COMMIT — drift
                    </span>
                  ) : (
                    // synthetic shas are "harmless0000<8 hex>" / "guiltyF3<8 hex>" --
                    // the numeric-prefix part repeats across rows, so slice past it
                    // (real GitHub 40-char hex shas are fine at any reasonable length)
                    <span title={c.commit_message ?? undefined}>
                      {c.commit_sha?.slice(0, 18)}
                    </span>
                  )}
                  {isTop && (
                    <span className="ml-2 rounded bg-indigo-700/50 px-1.5 py-0.5 text-indigo-200">
                      top suspect
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-3 text-slate-300">{c.hypothesized_category ?? "—"}</td>
                <td className="py-1.5 pr-3">
                  <ScoreBar value={c.provenance_score} color="bg-sky-500" />
                </td>
                <td className="py-1.5 pr-3">
                  <ScoreBar value={c.shape_match_score} color="bg-fuchsia-500" />
                </td>
                <td className="py-1.5 pr-3">
                  <ScoreBar value={c.combined_score} color="bg-emerald-500" />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
