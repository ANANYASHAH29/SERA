export interface ChartPoint {
  time: string;
  metric: number;
  status: string;
}

export function AccuracyChart({ points }: { points: ChartPoint[] }) {
  const width = 720;
  const height = 220;
  const padding = 32;
  const leftAxis = 44;

  const last = points.slice(-10);
  if (last.length < 2) {
    return (
      <p className="text-xs text-[#6B7280]">
        Not enough scans yet for a trend line ({last.length}/2 minimum) — submit another result to
        see this fill in.
      </p>
    );
  }

  const values = last.map((p) => p.metric);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = Math.max(maxVal - minVal, 0.01);
  const yPad = range * 0.15;
  const lo = Math.max(0, minVal - yPad);
  const hi = Math.min(1, maxVal + yPad);
  const span = Math.max(hi - lo, 0.01);

  const plotWidth = width - leftAxis - padding;
  const xStep = plotWidth / (last.length - 1);
  const toXY = (i: number, metric: number): [number, number] => {
    const x = leftAxis + i * xStep;
    const y = height - padding - ((metric - lo) / span) * (height - 2 * padding);
    return [x, y];
  };

  const pathD = last
    .map((p, i) => {
      const [x, y] = toXY(i, p.metric);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  // Baseline reference: the highest healthy value seen in the window --
  // what "recovered" is being measured against.
  const healthyValues = last.filter((p) => p.status !== "incident").map((p) => p.metric);
  const baseline = healthyValues.length > 0 ? Math.max(...healthyValues) : null;
  const baselineY = baseline != null ? toXY(0, baseline)[1] : null;

  const regressionIndex = last.findIndex((p, i) => i > 0 && p.status === "incident" && last[i - 1].status !== "incident");

  const yTicks = [hi, lo + span / 2, lo];

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      {yTicks.map((v, i) => {
        const y = height - padding - ((v - lo) / span) * (height - 2 * padding);
        return (
          <g key={i}>
            <line x1={leftAxis} y1={y} x2={width - padding} y2={y} stroke="#E5E7EB" strokeWidth={1} />
            <text x={leftAxis - 8} y={y + 3} textAnchor="end" fontSize="10" fill="#6B7280">
              {(v * 100).toFixed(0)}%
            </text>
          </g>
        );
      })}

      {baselineY != null && (
        <line
          x1={leftAxis}
          y1={baselineY}
          x2={width - padding}
          y2={baselineY}
          stroke="#9CA3AF"
          strokeWidth={1}
          strokeDasharray="3 3"
        />
      )}

      <path d={pathD} fill="none" stroke="#4F46E5" strokeWidth={2} />
      {last.map((p, i) => {
        const [x, y] = toXY(i, p.metric);
        const isIncident = p.status === "incident";
        return <circle key={i} cx={x} cy={y} r={isIncident ? 3.5 : 2.5} fill={isIncident ? "#DC2626" : "#4F46E5"} />;
      })}

      {regressionIndex >= 0 &&
        (() => {
          const [rx, ry] = toXY(regressionIndex, last[regressionIndex].metric);
          return (
            <g>
              <line x1={rx} y1={padding / 2} x2={rx} y2={height - padding} stroke="#DC2626" strokeWidth={1} strokeDasharray="4 2" />
              <circle cx={rx} cy={ry} r={5} fill="#DC2626" />
              <text x={rx + 6} y={padding / 2 + 10} fontSize="10" fill="#DC2626" fontWeight={600}>
                degradation
              </text>
            </g>
          );
        })()}
    </svg>
  );
}
