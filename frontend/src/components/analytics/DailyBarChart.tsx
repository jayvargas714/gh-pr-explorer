import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { useChartTheme } from './chartTheme'
import { formatNumber } from '../../utils/formatters'
import { ChartRow, formatDayTick, xTickProps } from '../../utils/analyticsSeries'

interface DailyBarChartProps {
  rows: ChartRow[]
  bars: { id: string; label: string; color: string; stackId?: string }[]
  height?: number
  yFormatter?: (v: number) => string
}

export function DailyBarChart({ rows, bars, height = 220, yFormatter = formatNumber }: DailyBarChartProps) {
  const { text, grid, tooltipStyle } = useChartTheme()

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows}>
        <CartesianGrid stroke={grid} />
        <XAxis
          dataKey="day"
          tickFormatter={(d) => formatDayTick(d, rows.length)}
          {...xTickProps(rows.length)}
          tick={{ fill: text, fontSize: 12 }}
        />
        <YAxis tickFormatter={yFormatter} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => yFormatter(Number(v))} />
        {bars.length > 1 && <Legend />}
        {bars.map((b) => (
          <Bar
            key={b.id}
            dataKey={b.id}
            name={b.label}
            fill={b.color}
            stackId={b.stackId}
            isAnimationActive={false}
            maxBarSize={24}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
