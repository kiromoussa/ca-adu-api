"use client";

export interface UsageBucket {
  label: string; // short axis label, e.g. "07-14"
  fullLabel: string; // e.g. "2026-07-14"
  count: number;
}

// Lightweight inline SVG bar chart. Avoids pulling in a charting dependency for
// a single view. Renders daily request counts for the trailing window.
export default function UsageChart({ data }: { data: UsageBucket[] }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const width = 720;
  const height = 220;
  const paddingLeft = 32;
  const paddingBottom = 28;
  const paddingTop = 10;
  const plotWidth = width - paddingLeft;
  const plotHeight = height - paddingBottom - paddingTop;
  const barGap = 3;
  const barWidth = data.length > 0 ? plotWidth / data.length - barGap : 0;

  const total = data.reduce((sum, d) => sum + d.count, 0);

  if (total === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-surface-border text-sm text-ink-soft">
        No API usage recorded yet.
      </div>
    );
  }

  const ticks = [0, Math.round(max / 2), max];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-auto w-full"
      role="img"
      aria-label="Daily API request usage"
    >
      {/* y-axis gridlines */}
      {ticks.map((t) => {
        const y = paddingTop + plotHeight - (t / max) * plotHeight;
        return (
          <g key={t}>
            <line
              x1={paddingLeft}
              y1={y}
              x2={width}
              y2={y}
              stroke="#e5e9f0"
              strokeWidth={1}
            />
            <text x={0} y={y + 3} fontSize={10} fill="#64748b">
              {t}
            </text>
          </g>
        );
      })}

      {/* bars */}
      {data.map((d, i) => {
        const barHeight = (d.count / max) * plotHeight;
        const x = paddingLeft + i * (barWidth + barGap);
        const y = paddingTop + plotHeight - barHeight;
        const showLabel = data.length <= 16 || i % 3 === 0;
        return (
          <g key={d.fullLabel}>
            <rect
              x={x}
              y={y}
              width={Math.max(1, barWidth)}
              height={barHeight}
              rx={2}
              fill="#2563eb"
            >
              <title>{`${d.fullLabel}: ${d.count} request(s)`}</title>
            </rect>
            {showLabel ? (
              <text
                x={x + barWidth / 2}
                y={height - 10}
                fontSize={9}
                fill="#64748b"
                textAnchor="middle"
              >
                {d.label}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}
