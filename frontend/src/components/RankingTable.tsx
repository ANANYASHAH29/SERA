import type { InterventionAttempt, RankedCandidateOut } from "../api";
import type { Theme } from "./StepCard";
import { verdictLabel } from "../scanSummary";

function ScoreBlocks({ value, theme }: { value: number; theme: Theme }) {
  const total = 10;
  const filled = Math.round(value * total);
  const filledColor = theme === "light" ? "bg-[#4F46E5]" : "bg-indigo-400";
  const emptyColor = theme === "light" ? "bg-[#E5E7EB]" : "bg-slate-800";
  const textClass = theme === "light" ? "text-[#6B7280]" : "text-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5">
        {Array.from({ length: total }, (_, i) => (
          <div key={i} className={`h-3 w-1.5 rounded-sm ${i < filled ? filledColor : emptyColor}`} />
        ))}
      </div>
      <span className={`w-9 text-right text-xs font-mono tabular-nums ${textClass}`}>{value.toFixed(2)}</span>
    </div>
  );
}

function statusLabel(
  rank: number,
  kind: string,
  light: boolean,
  attempt: InterventionAttempt | undefined
): { text: string; className: string } {
  if (attempt) {
    const verdict = attempt.verdict;
    if (verdict === "validated" || verdict === "validated_combined") {
      return { text: verdictLabel(verdict), className: light ? "bg-emerald-50 text-emerald-700" : "bg-emerald-950/50 text-emerald-300" };
    }
    if (verdict === "not_supported") {
      return { text: verdictLabel(verdict), className: light ? "bg-[#F7F8FA] text-[#6B7280]" : "bg-slate-800 text-slate-400" };
    }
    // insufficient_as_sole_cause / insufficient_combined
    return { text: verdictLabel(verdict), className: light ? "bg-amber-50 text-amber-700" : "bg-amber-950/50 text-amber-300" };
  }
  if (rank === 0) {
    return { text: "TOP SUSPECT", className: light ? "bg-red-50 text-red-700" : "bg-red-950/50 text-red-300" };
  }
  if (kind === "drift") {
    return { text: "ALTERNATIVE", className: light ? "bg-amber-50 text-amber-700" : "bg-amber-950/50 text-amber-300" };
  }
  return { text: "CANDIDATE", className: light ? "bg-[#F7F8FA] text-[#6B7280]" : "bg-slate-800 text-slate-400" };
}

export function RankingTable({
  candidates,
  theme = "dark",
  interventions = [],
}: {
  candidates: RankedCandidateOut[];
  theme?: Theme;
  interventions?: InterventionAttempt[];
}) {
  const light = theme === "light";
  const headClass = light ? "text-[#6B7280]" : "text-slate-500";
  const rowBorder = light ? "border-[#E5E7EB]" : "border-slate-800";
  const primaryText = light ? "text-[#111827]" : "text-slate-100";
  const mutedText = light ? "text-[#6B7280]" : "text-slate-500";

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className={headClass}>
            <th className="py-2 pr-3 font-medium">#</th>
            <th className="py-2 pr-3 font-medium">Hypothesis</th>
            <th className="py-2 pr-3 font-medium">Author</th>
            <th className="py-2 pr-3 font-medium">Category</th>
            <th className="py-2 pr-3 font-medium">Provenance</th>
            <th className="py-2 pr-3 font-medium">Shape match</th>
            <th className="py-2 pr-3 font-medium">Combined</th>
            <th className="py-2 pr-3 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => {
            const isDrift = c.kind === "drift";
            const attempt = interventions.find((a) => !a.combined && a.commit_sha === c.commit_sha);
            const status = statusLabel(c.rank, c.kind, light, attempt);
            return (
              <tr key={c.candidate_id} className={`border-t ${rowBorder}`}>
                <td className={`py-2.5 pr-3 font-mono ${mutedText}`}>{String(c.rank + 1).padStart(2, "0")}</td>
                <td className={`py-2.5 pr-3 font-mono font-medium ${primaryText}`}>
                  {isDrift ? "NO COMMIT — drift" : c.commit_sha?.slice(0, 10)}
                </td>
                <td className={`py-2.5 pr-3 ${primaryText}`}>{c.commit_author ?? "—"}</td>
                <td className={`py-2.5 pr-3 ${primaryText}`}>{c.stage_label ?? c.hypothesized_category ?? "—"}</td>
                <td className="py-2.5 pr-3">
                  <ScoreBlocks value={c.provenance_score} theme={theme} />
                </td>
                <td className="py-2.5 pr-3">
                  <ScoreBlocks value={c.shape_match_score} theme={theme} />
                </td>
                <td className="py-2.5 pr-3">
                  <ScoreBlocks value={c.combined_score} theme={theme} />
                </td>
                <td className="py-2.5 pr-3">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wide ${status.className}`}>
                    {status.text}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
