export interface ChartPoint {
  time: string;
  metric: number;
  status: string;
}

export function AccuracyChart({ points }: { points: ChartPoint[] }) {
  const width = 640;
  const height = 180;
  const padding = 24;

  const last = points.slice(-10);
  if (last.length < 2) {
    return (
      <p className="text-xs text-slate-400">
        Not enough scans yet for a trend line ({last.length}/2 minimum) — submit another result to
        see this fill in.
      </p>
    );
  }

  const values = last.map((p) => p.metric);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = Math.max(maxVal - minVal, 0.01);

  const xStep = (width - 2 * padding) / (last.length - 1);
  const toXY = (i: number, metric: number): [number, number] => {
    const x = padding + i * xStep;
    const y = height - padding - ((metric - minVal) / range) * (height - 2 * padding);
    return [x, y];
  };

  const pathD = last
    .map((p, i) => {
      const [x, y] = toXY(i, p.metric);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const regressionIndex = last.findIndex((p, i) => i > 0 && p.status === "incident" && last[i - 1].status !== "incident");

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <path d={pathD} fill="none" stroke="#3b82f6" strokeWidth={2} />
      {last.map((p, i) => {
        const [x, y] = toXY(i, p.metric);
        return <circle key={i} cx={x} cy={y} r={2.5} fill="#3b82f6" />;
      })}
      {regressionIndex >= 0 &&
        (() => {
          const [rx] = toXY(regressionIndex, last[regressionIndex].metric);
          const [, ry] = toXY(regressionIndex, last[regressionIndex].metric);
          return (
            <g>
              <line x1={rx} y1={padding / 2} x2={rx} y2={height - padding} stroke="#ef4444" strokeWidth={1} strokeDasharray="4 2" />
              <circle cx={rx} cy={ry} r={5} fill="#ef4444" />
            </g>
          );
        })()}
    </svg>
  );
}
