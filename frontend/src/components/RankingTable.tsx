import type { RankedCandidateOut } from "../api";
import type { Theme } from "./StepCard";

function ScoreBar({ value, color, theme }: { value: number; color: string; theme: Theme }) {
  const trackClass = theme === "light" ? "bg-slate-200" : "bg-slate-800";
  const textClass = theme === "light" ? "text-slate-500" : "text-slate-400";
  return (
    <div className="flex items-center gap-2">
      <div className={`h-1.5 w-16 overflow-hidden rounded-full ${trackClass}`}>
        <div className={`h-full ${color}`} style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className={`w-10 text-right text-xs tabular-nums ${textClass}`}>{value.toFixed(2)}</span>
    </div>
  );
}

export function RankingTable({
  candidates,
  theme = "dark",
}: {
  candidates: RankedCandidateOut[];
  theme?: Theme;
}) {
  const light = theme === "light";
  const headClass = light ? "text-slate-500" : "text-slate-500";
  const rowBorder = light ? "border-slate-200" : "border-slate-800";
  const topRowBg = light ? "bg-indigo-50" : "bg-indigo-950/30";
  const rankTextClass = light ? "text-slate-400" : "text-slate-500";
  const categoryClass = light ? "text-slate-600" : "text-slate-300";
  const driftBadge = light
    ? "bg-amber-100 text-amber-800"
    : "bg-amber-900/40 text-amber-300";
  const topBadge = light
    ? "bg-indigo-100 text-indigo-700"
    : "bg-indigo-700/50 text-indigo-200";

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className={headClass}>
            <th className="py-1 pr-3 font-medium">#</th>
            <th className="py-1 pr-3 font-medium">Candidate</th>
            <th className="py-1 pr-3 font-medium">Author</th>
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
                className={`border-t ${rowBorder} ${isTop ? topRowBg : ""}`}
              >
                <td className={`py-1.5 pr-3 ${rankTextClass}`}>{c.rank + 1}</td>
                <td className="py-1.5 pr-3 font-mono">
                  {isDrift ? (
                    <span className={`rounded px-1.5 py-0.5 ${driftBadge}`}>
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
                  {isTop && <span className={`ml-2 rounded px-1.5 py-0.5 ${topBadge}`}>top suspect</span>}
                </td>
                <td className={`py-1.5 pr-3 ${categoryClass}`}>{c.commit_author ?? "—"}</td>
                <td className={`py-1.5 pr-3 ${categoryClass}`}>
                  {c.stage_label ?? c.hypothesized_category ?? "—"}
                </td>
                <td className="py-1.5 pr-3">
                  <ScoreBar value={c.provenance_score} color="bg-sky-500" theme={theme} />
                </td>
                <td className="py-1.5 pr-3">
                  <ScoreBar value={c.shape_match_score} color="bg-fuchsia-500" theme={theme} />
                </td>
                <td className="py-1.5 pr-3">
                  <ScoreBar value={c.combined_score} color="bg-emerald-500" theme={theme} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
