import type { WorkflowArtifact } from '../../api/workflow-engine'

interface PublishPreviewProps {
  artifacts: WorkflowArtifact[]
}

function parseContent(artifact: WorkflowArtifact): Record<string, unknown> | null {
  const raw = artifact.content_json
  if (!raw) return null
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return null }
  }
  return raw as Record<string, unknown>
}

export function PublishPreview({ artifacts }: PublishPreviewProps) {
  const publishArtifact = artifacts.find((a) => a.artifact_type === 'publish' || a.artifact_type === 'comment')
  const synthArtifact = artifacts.find((a) => a.artifact_type === 'synthesis')

  let markdown: string | null = null

  if (publishArtifact) {
    const content = parseContent(publishArtifact)
    markdown = (content?.body ?? content?.comment ?? content?.markdown ?? null) as string | null
  }

  if (!markdown && synthArtifact) {
    const content = parseContent(synthArtifact)
    if (content) {
      const verdict = content.verdict as string ?? 'COMMENT'
      const summary = content.summary as string ?? ''
      const agreed = (content.agreed ?? []) as Array<Record<string, unknown>>
      const aOnly = ((content.a_only ?? content['A-ONLY'] ?? []) as Array<Record<string, unknown>>)
      const bOnly = ((content.b_only ?? content['B-ONLY'] ?? []) as Array<Record<string, unknown>>)

      const lines: string[] = []
      lines.push(`## Code Review — ${verdict}`)
      lines.push('')
      if (summary) lines.push(summary)
      lines.push('')

      const allFindings: Array<{ finding: Record<string, unknown>; cls: string }> = [
        ...agreed.map((f) => ({ finding: f, cls: 'Agreed' })),
        ...aOnly.map((f) => ({ finding: f, cls: 'A-Only' })),
        ...bOnly.map((f) => ({ finding: f, cls: 'B-Only' })),
      ]

      if (allFindings.length > 0) {
        lines.push('### Findings')
        lines.push('')
        for (const { finding: f, cls } of allFindings) {
          const sev = (f.severity as string) ?? 'minor'
          const title = (f.title as string) ?? 'Untitled'
          const loc = (f.location as Record<string, unknown>)?.file as string ?? ''
          lines.push(`- **[${sev}]** ${title}${loc ? ` (\`${loc}\`)` : ''} — _${cls}_`)
          if (f.problem) lines.push(`  ${f.problem}`)
        }
      }

      markdown = lines.join('\n')
    }
  }

  if (!markdown) {
    return <p className="mx-publish-preview__empty">No publish preview available yet. The publish step generates the final GitHub comment.</p>
  }

  return (
    <div className="mx-publish-preview">
      <div className="mx-publish-preview__header">
        <h5>GitHub Comment Preview</h5>
        <span className="mx-publish-preview__note">This is what will be posted to the PR.</span>
      </div>
      <div className="mx-publish-preview__body">
        <pre className="mx-publish-preview__md">{markdown}</pre>
      </div>
    </div>
  )
}
