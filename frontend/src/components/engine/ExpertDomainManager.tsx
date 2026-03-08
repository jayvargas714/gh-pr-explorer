import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import {
  listExpertDomains,
  createExpertDomain,
  updateExpertDomain,
  deleteExpertDomain,
  type ExpertDomain,
} from '../../api/workflow-engine'

interface ExpertDomainManagerProps {
  onClose: () => void
}

export function ExpertDomainManager({ onClose }: ExpertDomainManagerProps) {
  const [domains, setDomains] = useState<ExpertDomain[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newDomain, setNewDomain] = useState({
    domain_id: '', display_name: '', persona: '', scope: '',
    triggers: { file_patterns: [] as string[], keywords: [] as string[] },
    checklist: [] as string[], anti_patterns: [] as string[],
  })

  const [error, setError] = useState<string | null>(null)

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listExpertDomains()
      setDomains(data)
    } catch (e) {
      setError(`Failed to load domains: ${e}`)
    }
    setLoading(false)
  }

  useEffect(() => { refresh() }, [])

  const handleToggleActive = async (d: ExpertDomain) => {
    await updateExpertDomain(d.domain_id, { is_active: !d.is_active } as Partial<ExpertDomain>)
    refresh()
  }

  const handleDelete = async (d: ExpertDomain) => {
    if (d.is_builtin) return
    if (!confirm(`Delete custom domain "${d.display_name}"?`)) return
    await deleteExpertDomain(d.domain_id)
    refresh()
  }

  const handleCreate = async () => {
    if (!newDomain.domain_id.trim()) return
    await createExpertDomain(newDomain)
    setCreating(false)
    setNewDomain({
      domain_id: '', display_name: '', persona: '', scope: '',
      triggers: { file_patterns: [], keywords: [] },
      checklist: [], anti_patterns: [],
    })
    refresh()
  }

  if (loading) return <div className="mx-domain-mgr"><Spinner /> Loading domains...</div>

  return (
    <div className="mx-domain-mgr">
      {error && (
        <div className="mx-alert mx-alert--error" style={{ marginBottom: 'var(--mx-space-4)' }}>
          <div className="mx-alert__content">{error}</div>
          <button className="mx-alert__close" onClick={() => setError(null)}>x</button>
        </div>
      )}
      <div className="mx-domain-mgr__header">
        <h3>Expert Domain Catalog</h3>
        <div>
          <Button variant="primary" size="sm" onClick={() => setCreating(true)}>+ New Domain</Button>
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
      </div>

      {creating && (
        <div className="mx-domain-mgr__create">
          <h4>New Custom Domain</h4>
          <input className="mx-input" placeholder="domain_id (e.g. my-domain)"
            value={newDomain.domain_id}
            onChange={e => setNewDomain(p => ({ ...p, domain_id: e.target.value }))} />
          <input className="mx-input" placeholder="Display Name"
            value={newDomain.display_name}
            onChange={e => setNewDomain(p => ({ ...p, display_name: e.target.value }))} />
          <textarea className="mx-input" placeholder="Persona description..." rows={3}
            value={newDomain.persona}
            onChange={e => setNewDomain(p => ({ ...p, persona: e.target.value }))} />
          <input className="mx-input" placeholder="Scope"
            value={newDomain.scope}
            onChange={e => setNewDomain(p => ({ ...p, scope: e.target.value }))} />
          <div className="mx-domain-mgr__create-actions">
            <Button variant="primary" size="sm" onClick={handleCreate}>Create</Button>
            <Button variant="ghost" size="sm" onClick={() => setCreating(false)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="mx-domain-mgr__list">
        {domains.map(d => {
          const isOpen = expandedId === d.domain_id
          return (
            <div key={d.domain_id} className={`mx-domain-mgr__item ${!d.is_active ? 'mx-domain-mgr__item--inactive' : ''}`}>
              <div className="mx-domain-mgr__item-header" onClick={() => setExpandedId(isOpen ? null : d.domain_id)}>
                <span className="mx-domain-mgr__item-toggle">{isOpen ? '▼' : '▶'}</span>
                <strong>{d.display_name}</strong>
                <code className="mx-domain-mgr__item-id">{d.domain_id}</code>
                {d.is_builtin && <Badge variant="neutral" size="sm">Built-in</Badge>}
                <Badge variant={d.is_active ? 'success' : 'neutral'} size="sm">
                  {d.is_active ? 'Active' : 'Disabled'}
                </Badge>
                <span className="mx-domain-mgr__item-stats">
                  {d.checklist?.length ?? 0} checks, {d.anti_patterns?.length ?? 0} anti-patterns
                </span>
              </div>
              {isOpen && (
                <div className="mx-domain-mgr__item-detail">
                  <div className="mx-domain-mgr__section">
                    <strong>Persona</strong>
                    <p>{d.persona}</p>
                  </div>
                  <div className="mx-domain-mgr__section">
                    <strong>Scope:</strong> {d.scope}
                  </div>
                  {d.triggers && (
                    <div className="mx-domain-mgr__section">
                      <strong>Triggers</strong>
                      {d.triggers.file_patterns?.length > 0 && (
                        <div>Files: {d.triggers.file_patterns.map((p, i) =>
                          <code key={i} className="mx-domain-mgr__trigger">{p}</code>
                        )}</div>
                      )}
                      {d.triggers.keywords?.length > 0 && (
                        <div>Keywords: {d.triggers.keywords.map((k, i) =>
                          <code key={i} className="mx-domain-mgr__trigger">{k}</code>
                        )}</div>
                      )}
                    </div>
                  )}
                  {d.checklist?.length > 0 && (
                    <div className="mx-domain-mgr__section">
                      <strong>Checklist</strong>
                      <ol>{d.checklist.map((c, i) => <li key={i}>{c}</li>)}</ol>
                    </div>
                  )}
                  {d.anti_patterns?.length > 0 && (
                    <div className="mx-domain-mgr__section">
                      <strong>Anti-Patterns</strong>
                      <ul>{d.anti_patterns.map((p, i) => <li key={i}>{p}</li>)}</ul>
                    </div>
                  )}
                  <div className="mx-domain-mgr__item-actions">
                    <Button variant="ghost" size="sm" onClick={() => handleToggleActive(d)}>
                      {d.is_active ? 'Disable' : 'Enable'}
                    </Button>
                    {!d.is_builtin && (
                      <Button variant="danger" size="sm" onClick={() => handleDelete(d)}>
                        Delete
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
