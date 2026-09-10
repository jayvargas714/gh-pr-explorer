import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useChartTheme } from './chartTheme'
import { formatNumber } from '../../utils/formatters'
import { ChartRow, SeriesSpec, formatDayTick, xTickProps } from '../../utils/analyticsSeries'

interface TimeSeriesChartProps {
  rows: ChartRow[]
  series: SeriesSpec[]
  hidden: ReadonlySet<string>
  onToggle: (id: string) => void
  height?: number
  yFormatter?: (v: number) => string
  emptyHint?: string
}

export function TimeSeriesChart({
  rows,
  series,
  hidden,
  onToggle,
  height = 400,
  yFormatter = formatNumber,
  emptyHint,
}: TimeSeriesChartProps) {
  const { text, grid, tooltipStyle } = useChartTheme()
  const allHidden = series.length > 0 && series.every((s) => hidden.has(s.id))

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows}>
          <CartesianGrid stroke={grid} />
          <XAxis
            dataKey="day"
            tickFormatter={(d) => formatDayTick(d, rows.length)}
            {...xTickProps(rows.length)}
            tick={{ fill: text, fontSize: 12 }}
          />
          <YAxis tickFormatter={yFormatter} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v) => yFormatter(Number(v))} />
          <Legend
            onClick={(item) => onToggle(String(item.dataKey))}
            wrapperStyle={{ cursor: 'pointer', fontSize: 12 }}
          />
          {series.map((s) => (
            <Line
              key={s.id}
              dataKey={s.id}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              type="monotone"
              connectNulls
              isAnimationActive={false}
              dot={rows.length <= 2 ? { r: 4 } : false}
              hide={hidden.has(s.id)}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      {series.length === 0 && <p className="mx-analytics__hint">Pick at least one metric and one person</p>}
      {series.length > 0 && allHidden && (
        <p className="mx-analytics__hint">All series hidden &mdash; click a legend entry to show it</p>
      )}
      {rows.length === 0 && <p className="mx-analytics__hint">{emptyHint ?? 'No days in this window'}</p>}
      {rows.length === 1 && (
        <p className="mx-analytics__hint">
          Single-day window: one point per series. Widen the window to see a trend.
        </p>
      )}
    </div>
  )
}
