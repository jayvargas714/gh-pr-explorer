import { useEffect, useState } from 'react'
import { fetchAuditHistory } from '../../api/audits'
import type { AuditHistoryItem } from '../../api/types'
import { AuditChip } from './AuditChip'
import { AuditViewer } from './AuditViewer'
import { Input } from '../common/Input'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

export function AuditHistoryList() {
  const [items, setItems] = useState<AuditHistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchAuditHistory({ search: search || undefined, limit: 50 })
      .then((r) => {
        if (!cancelled) setItems(r.audits)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load audit history')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [search])

  return (
    <div className="mx-audit-history">
      <div className="mx-history-panel__filters">
        <Input
          label="Search"
          placeholder="Search audits..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading && items.length === 0 ? (
        <div className="mx-history-panel__loading">
          <Spinner size="md" />
          <p>Loading audits...</p>
        </div>
      ) : error ? (
        <Alert variant="error">{error}</Alert>
      ) : items.length === 0 ? (
        <Alert variant="info">No audits found matching the current filters.</Alert>
      ) : (
        <ul className="mx-audit-history__list">
          {items.map((a) => (
            <li key={a.id} className="mx-audit-history__row">
              <button type="button" className="mx-link" onClick={() => setOpenId(a.id)}>
                PR #{a.pr_number} — {a.pr_title || a.repo}
              </button>
              <span className="mx-audit-history__meta">{a.repo}</span>
              {a.status === 'failed' ? (
                <span className="mx-audit-failed-badge" title="The audit process failed to complete">
                  Failed
                </span>
              ) : (
                <AuditChip
                  findingCount={a.finding_count}
                  blockingCount={a.blocking_count}
                  onClick={() => setOpenId(a.id)}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      {openId !== null && <AuditViewer auditId={openId} onClose={() => setOpenId(null)} />}
    </div>
  )
}
