interface InfoTooltipProps {
  text: string
}

export function InfoTooltip({ text }: InfoTooltipProps) {
  return (
    <span className="mx-info-tooltip">
      <span className="mx-info-tooltip__icon">?</span>
      <span className="mx-info-tooltip__content">{text}</span>
    </span>
  )
}
