interface BarChartProps {
  title: string
  data: Array<{ label: string; value: number }>
  color?: string
}

export function BarChart({ title, data, color = 'var(--mx-color-primary)' }: BarChartProps) {
  const maxValue = Math.max(...data.map((d) => d.value))

  return (
    <div className="mx-activity__chart">
      <h3>{title}</h3>
      <div className="mx-bar-chart">
        {data.map((item, i) => (
          <div key={i} className="mx-bar-chart__bar">
            <div
              className="mx-bar-chart__fill"
              style={{
                height: `${(item.value / maxValue) * 100}%`,
                backgroundColor: color,
              }}
              title={`${item.label}: ${item.value}`}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
