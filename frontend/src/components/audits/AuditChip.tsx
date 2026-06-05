interface AuditChipProps {
  findingCount: number
  blockingCount: number
  /** Optional dominant blocking severity label, e.g. "scope-violation". */
  blockingLabel?: string
  onClick?: () => void
  title?: string
}

export function AuditChip({ findingCount, blockingCount, blockingLabel, onClick, title }: AuditChipProps) {
  const blocking = blockingCount > 0
  const label = blocking
    ? `Audit · ${blockingCount} ${blockingLabel || 'blocking'}`
    : `Audit · 0 blocking`
  return (
    <button
      type="button"
      className={`mx-audit-chip ${blocking ? 'mx-audit-chip--blocking' : 'mx-audit-chip--clean'}`}
      onClick={onClick}
      title={title || `${findingCount} finding(s), ${blockingCount} blocking`}
    >
      {label}
    </button>
  )
}
