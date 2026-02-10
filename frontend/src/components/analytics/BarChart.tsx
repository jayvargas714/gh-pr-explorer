import { InfoTooltip } from '../common/InfoTooltip'

interface BarChartProps {
  title: string
  data: Array<{ label: string; value: number }>
  color?: string
  tooltip?: string
}

export function BarChart({ title, data, color = 'var(--mx-color-primary)', tooltip }: BarChartProps) {
  const maxValue = Math.max(1, ...data.map((d) => d.value))

  return (
    <div className="mx-activity__chart">
      <h3>{title}{tooltip && <InfoTooltip text={tooltip} />}</h3>
      <div className="mx-bar-chart">
        {data.map((item, i) => (
          <div key={i} className="mx-bar-chart__bar">
            <div
              className="mx-bar-chart__fill"
              style={{
                height: `${(item.value / maxValue) * 100}%`,
                backgroundColor: color,
              }}
              data-tooltip={`${item.label}: ${item.value}`}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
