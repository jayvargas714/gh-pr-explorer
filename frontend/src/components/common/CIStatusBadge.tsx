import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { Badge } from './Badge'
import type { StatusCheck } from '../../api/types'

interface CIStatusBadgeProps {
  ciStatus: string | null
  statusCheckRollup?: StatusCheck[] | null
}

interface NormalizedCheck {
  key: string
  name: string
  workflowName: string | null
  description: string | null
  detailsUrl: string | null
  conclusion: string
  durationMs: number | null
}

const FAILURE_CONCLUSIONS = new Set(['FAILURE', 'TIMED_OUT', 'ACTION_REQUIRED'])
const FAILURE_STATES = new Set(['FAILURE', 'ERROR'])

function dedupeChecks(checks: StatusCheck[]): StatusCheck[] {
  const latest = new Map<string, StatusCheck>()
  checks.forEach((check, idx) => {
    const name = check.name || check.context || `__unnamed_${idx}`
    const existing = latest.get(name)
    if (!existing) {
      latest.set(name, check)
      return
    }
    const newTime = check.completedAt || check.startedAt || ''
    const oldTime = existing.completedAt || existing.startedAt || ''
    if (newTime >= oldTime) latest.set(name, check)
  })
  return Array.from(latest.values())
}

function isFailing(check: StatusCheck): boolean {
  const conclusion = (check.conclusion || '').toUpperCase()
  if (conclusion) return FAILURE_CONCLUSIONS.has(conclusion)
  const state = (check.state || '').toUpperCase()
  if (state) return FAILURE_STATES.has(state)
  return false
}

function normalize(check: StatusCheck, idx: number): NormalizedCheck {
  const name = check.name || check.context || 'Check'
  const conclusion = (check.conclusion || check.state || '').toUpperCase() || 'FAILURE'
  let durationMs: number | null = null
  if (check.startedAt && check.completedAt) {
    const start = Date.parse(check.startedAt)
    const end = Date.parse(check.completedAt)
    if (!Number.isNaN(start) && !Number.isNaN(end) && end >= start) {
      durationMs = end - start
    }
  }
  return {
    key: `${name}-${idx}`,
    name,
    workflowName: check.workflowName || null,
    description: check.description || null,
    detailsUrl: check.detailsUrl || check.targetUrl || null,
    conclusion,
    durationMs,
  }
}

function formatDuration(ms: number): string {
  const totalSec = Math.round(ms / 1000)
  if (totalSec < 60) return `${totalSec}s`
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  if (min < 60) return sec === 0 ? `${min}m` : `${min}m ${sec}s`
  const hr = Math.floor(min / 60)
  const remMin = min % 60
  return remMin === 0 ? `${hr}h` : `${hr}h ${remMin}m`
}

const CONCLUSION_LABEL: Record<string, string> = {
  FAILURE: 'Failed',
  TIMED_OUT: 'Timed out',
  ACTION_REQUIRED: 'Action required',
  ERROR: 'Error',
}

const CONCLUSION_ICON: Record<string, string> = {
  FAILURE: '✗',
  TIMED_OUT: '⏱',
  ACTION_REQUIRED: '⚠',
  ERROR: '⚠',
}

export function CIStatusBadge({ ciStatus, statusCheckRollup }: CIStatusBadgeProps) {
  const [showPopup, setShowPopup] = useState(false)
  const [popupPos, setPopupPos] = useState({ x: 0, y: 0 })
  const badgeRef = useRef<HTMLSpanElement>(null)
  const hideTimeout = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (hideTimeout.current) clearTimeout(hideTimeout.current)
    }
  }, [])

  if (!ciStatus) return null
  const lower = ciStatus.toLowerCase()

  const renderBadge = () => {
    switch (lower) {
      case 'success':
        return <Badge variant="success">✓ CI Passed</Badge>
      case 'failure':
        return <Badge variant="error">✗ CI Failed</Badge>
      case 'pending':
        return <Badge variant="warning">⏳ CI Running</Badge>
      default:
        return <Badge variant="neutral">CI Skipped</Badge>
    }
  }

  const failedChecks: NormalizedCheck[] =
    lower === 'failure' && statusCheckRollup && statusCheckRollup.length > 0
      ? dedupeChecks(statusCheckRollup).filter(isFailing).map(normalize)
      : []

  if (failedChecks.length === 0) return renderBadge()

  const handleEnter = () => {
    if (hideTimeout.current) {
      clearTimeout(hideTimeout.current)
      hideTimeout.current = null
    }
    if (badgeRef.current) {
      const rect = badgeRef.current.getBoundingClientRect()
      setPopupPos({ x: rect.left + rect.width / 2, y: rect.bottom + 6 })
    }
    setShowPopup(true)
  }

  const handleLeave = () => {
    hideTimeout.current = window.setTimeout(() => setShowPopup(false), 150)
  }

  const handlePopupEnter = () => {
    if (hideTimeout.current) {
      clearTimeout(hideTimeout.current)
      hideTimeout.current = null
    }
  }

  const handlePopupLeave = () => {
    hideTimeout.current = window.setTimeout(() => setShowPopup(false), 150)
  }

  return (
    <>
      <span
        ref={badgeRef}
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
        className="mx-ci-badge-trigger"
      >
        {renderBadge()}
      </span>
      {showPopup &&
        createPortal(
          <div
            className="mx-ci-popup"
            style={{ left: popupPos.x, top: popupPos.y }}
            onMouseEnter={handlePopupEnter}
            onMouseLeave={handlePopupLeave}
          >
            <div className="mx-ci-popup__header">
              {failedChecks.length} failing {failedChecks.length === 1 ? 'check' : 'checks'}
            </div>
            <div className="mx-ci-popup__list">
              {failedChecks.map((check) => {
                const label = CONCLUSION_LABEL[check.conclusion] || 'Failed'
                const icon = CONCLUSION_ICON[check.conclusion] || '✗'
                const subtitle = [check.workflowName, check.description]
                  .filter((v): v is string => !!v && v !== check.name)
                  .join(' · ')
                const inner = (
                  <>
                    <span className="mx-ci-popup__icon" aria-hidden>
                      {icon}
                    </span>
                    <div className="mx-ci-popup__info">
                      <span className="mx-ci-popup__name">{check.name}</span>
                      {subtitle && <span className="mx-ci-popup__subtitle">{subtitle}</span>}
                      <span className="mx-ci-popup__meta">
                        {label}
                        {check.durationMs !== null && ` · ${formatDuration(check.durationMs)}`}
                      </span>
                    </div>
                    {check.detailsUrl && (
                      <span className="mx-ci-popup__arrow" aria-hidden>
                        ↗
                      </span>
                    )}
                  </>
                )

                return check.detailsUrl ? (
                  <a
                    key={check.key}
                    href={check.detailsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mx-ci-popup__item mx-ci-popup__item--link"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {inner}
                  </a>
                ) : (
                  <div key={check.key} className="mx-ci-popup__item">
                    {inner}
                  </div>
                )
              })}
            </div>
          </div>,
          document.body
        )}
    </>
  )
}
