import { api } from './client'
import {
  ActiveAuditsResponse,
  AuditHistoryResponse,
  AuditDetail,
  MessageResponse,
} from './types'

/** Fetch active/recent audits (drives the spinner). */
export async function fetchActiveAudits(): Promise<ActiveAuditsResponse> {
  return api.get<ActiveAuditsResponse>('/audits')
}

/** Start a PB↔ED audit for a PR. */
export async function startAudit(data: {
  number: number
  url: string
  owner: string
  repo: string
  title?: string
  author?: string
  head_ref?: string
  base_ref?: string
}): Promise<{ message: string; key: string; status: string; audit_file: string }> {
  return api.post('/audits', data)
}

/** Cancel a running audit. */
export async function cancelAudit(
  owner: string,
  repo: string,
  prNumber: number,
): Promise<MessageResponse> {
  return api.delete<MessageResponse>(`/audits/${owner}/${repo}/${prNumber}`)
}

/** Fetch audit history with filters. */
export async function fetchAuditHistory(params: {
  repo?: string
  author?: string
  pr_number?: number
  search?: string
  limit?: number
  offset?: number
}): Promise<AuditHistoryResponse> {
  const qp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qp.append(k, String(v))
  })
  const qs = qp.toString()
  return api.get<AuditHistoryResponse>(`/audit-history${qs ? `?${qs}` : ''}`)
}

/** Get an audit detail by ID. */
export async function getAuditDetail(auditId: number): Promise<AuditDetail> {
  const response = await api.get<{ audit: AuditDetail }>(`/audit-history/${auditId}`)
  return response.audit
}

/** Check whether a PR has been audited. */
export async function checkPRAudited(owner: string, repo: string, prNumber: number) {
  return api.get(`/audit-history/check/${owner}/${repo}/${prNumber}`)
}

/** Post audit findings (with file+line) as inline PR comments. */
export async function postAuditInlineComments(auditId: number): Promise<MessageResponse> {
  return api.post<MessageResponse>(`/audits/${auditId}/post-inline-comments`, {})
}
