import { Badge } from '../common/Badge'

interface Finding {
  title?: string
  severity?: string
  location?: { file?: string; start_line?: number; end_line?: number; raw?: string }
  problem?: string
  fix?: string
}

interface FindingCardProps {
  finding: Finding
  classification?: string
  source?: string
}

const SEVERITY_VARIANT: Record<string, 'error' | 'warning' | 'neutral'> = {
  critical: 'error',
  major: 'warning',
  minor: 'neutral',
}

export function FindingCard({ finding, classification, source }: FindingCardProps) {
  const loc = finding.location
  const locStr = loc?.file
    ? `${loc.file}${loc.start_line ? `:${loc.start_line}` : ''}${loc.end_line ? `-${loc.end_line}` : ''}`
    : loc?.raw ?? ''

  return (
    <div className="mx-finding">
      <div className="mx-finding__header">
        <Badge variant={SEVERITY_VARIANT[finding.severity ?? ''] ?? 'neutral'} size="sm">
          {finding.severity ?? 'minor'}
        </Badge>
        <span className="mx-finding__title">{finding.title ?? 'Untitled'}</span>
        {classification && (
          <Badge
            variant={classification === 'AGREED' ? 'success' : 'warning'}
            size="sm"
          >
            {classification}
          </Badge>
        )}
        {source && <span className="mx-finding__source">{source}</span>}
      </div>
      {locStr && (
        <code className="mx-finding__location">{locStr}</code>
      )}
      {finding.problem && (
        <p className="mx-finding__problem">{finding.problem}</p>
      )}
      {finding.fix && (
        <div className="mx-finding__fix">
          <strong>Fix:</strong> {finding.fix}
        </div>
      )}
    </div>
  )
}
