import { api } from './client'

export interface WorkflowTemplate {
  id: number
  name: string
  description: string
  template_json?: string
  template?: Record<string, unknown>
  is_builtin: boolean
  created_at: string
  updated_at: string
}

export interface WorkflowStep {
  id: number
  instance_id: number
  step_id: string
  step_type: string
  status: string
  started_at?: string
  completed_at?: string
  error_message?: string
  outputs_json?: string | null
  step_config_json?: string | null
  agent_id?: number | null
  inputs_json?: string | null
}

export interface WorkflowArtifact {
  id: number
  instance_id: number
  step_id: string
  pr_number?: number
  artifact_type: string
  file_path?: string
  content_json?: string | Record<string, unknown> | null
  created_at: string
}

export interface WorkflowInstance {
  id: number
  template_id: number
  template_name: string
  repo: string
  status: string
  config_json?: string
  created_at: string
  updated_at: string
  steps?: WorkflowStep[]
  artifacts?: WorkflowArtifact[]
}

export interface Agent {
  id: number
  name: string
  type: string
  model: string
  is_active: boolean
}

export async function listTemplates(): Promise<WorkflowTemplate[]> {
  return api.get<WorkflowTemplate[]>('/templates')
}

export async function getTemplate(id: number): Promise<WorkflowTemplate> {
  return api.get<WorkflowTemplate>(`/templates/${id}`)
}

export async function createTemplate(data: {
  name: string
  description?: string
  template: Record<string, unknown>
}): Promise<{ id: number }> {
  return api.post('/templates', data)
}

export async function cloneTemplate(id: number, name?: string): Promise<{ id: number }> {
  return api.post(`/templates/${id}/clone`, name ? { name } : {})
}

export async function validateTemplate(id: number): Promise<{ valid: boolean; errors: string[] }> {
  return api.post(`/templates/${id}/validate`, {})
}

export async function deleteTemplate(id: number): Promise<{ ok: boolean }> {
  return api.delete(`/templates/${id}`)
}

export async function runWorkflow(data: {
  template_id: number
  repo: string
  config?: Record<string, unknown>
}): Promise<{ id: number; status: string }> {
  return api.post('/workflows/run', data)
}

export async function listInstances(repo?: string): Promise<WorkflowInstance[]> {
  const params = repo ? `?repo=${encodeURIComponent(repo)}` : ''
  return api.get<WorkflowInstance[]>(`/workflows/instances${params}`)
}

export async function getInstance(id: number): Promise<WorkflowInstance> {
  return api.get<WorkflowInstance>(`/workflows/instances/${id}`)
}

export async function gateAction(
  instanceId: number,
  action: 'approve' | 'reject',
  data?: Record<string, unknown>
): Promise<{ ok: boolean; status: string }> {
  return api.post(`/workflows/instances/${instanceId}/gate`, { action, ...data })
}

export async function cancelInstance(id: number): Promise<{ ok: boolean }> {
  return api.delete(`/workflows/instances/${id}`)
}

export async function listAgents(): Promise<Agent[]> {
  return api.get<Agent[]>('/agents')
}

export async function getAvailableStepTypes(): Promise<{ available: string[] }> {
  return api.get<{ available: string[] }>('/step-types')
}

export async function getStepLiveOutput(instanceId: number, stepId: string): Promise<string> {
  const res = await api.get<{ output: string }>(`/workflows/instances/${instanceId}/steps/${stepId}/live`)
  return res.output
}

export async function retryStep(instanceId: number, stepId: string): Promise<{ ok: boolean; status: string }> {
  return api.post(`/workflows/instances/${instanceId}/steps/${stepId}/retry`, {})
}

export function getStepDownloadUrl(instanceId: number, stepId: string, format: 'md' | 'json' = 'md'): string {
  return `/api/workflows/instances/${instanceId}/steps/${stepId}/download?format=${format}`
}

// --- Expert Domains ---

export interface ExpertDomain {
  id: number
  domain_id: string
  display_name: string
  persona: string
  scope: string
  triggers: { file_patterns: string[]; keywords: string[] }
  checklist: string[]
  anti_patterns: string[]
  is_builtin: boolean
  is_active: boolean
}

export async function listExpertDomains(): Promise<ExpertDomain[]> {
  return api.get<ExpertDomain[]>('/expert-domains')
}

export async function createExpertDomain(data: Partial<ExpertDomain>): Promise<{ id: number }> {
  return api.post('/expert-domains', data)
}

export async function updateExpertDomain(domainId: string, data: Partial<ExpertDomain>): Promise<{ ok: boolean }> {
  return api.put(`/expert-domains/${domainId}`, data)
}

export async function deleteExpertDomain(domainId: string): Promise<{ ok: boolean }> {
  return api.delete(`/expert-domains/${domainId}`)
}

// --- Follow-ups ---

export interface FollowupFinding {
  id: number
  finding_id: string
  original_text: string
  severity: string
  status: string
  author_response?: string
}

export interface ReviewFollowup {
  id: number
  instance_id: number
  pr_number: number
  repo: string
  source_run_id: number
  verdict: string
  published_at: string
  review_sha: string
  status: string
  last_checked: string
  notes?: string
  findings?: FollowupFinding[]
}

export async function listFollowups(repo?: string): Promise<ReviewFollowup[]> {
  const params = repo ? `?repo=${encodeURIComponent(repo)}` : ''
  return api.get<ReviewFollowup[]>(`/followups${params}`)
}

export async function getFollowup(id: number): Promise<ReviewFollowup> {
  return api.get<ReviewFollowup>(`/followups/${id}`)
}
