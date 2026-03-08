import { useState } from 'react'
import { WorkflowRunList } from './WorkflowRunList'
import { WorkflowRunDetail } from './WorkflowRunDetail'
import { RunConfigPanel } from './RunConfigPanel'
import { GateView } from './GateView'
import { ExpertDomainManager } from './ExpertDomainManager'
import { FollowUpTracker } from './FollowUpTracker'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { useAccountStore } from '../../stores/useAccountStore'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import type { WorkflowInstance } from '../../api/workflow-engine'

type View = 'list' | 'config' | 'detail' | 'gate' | 'domains' | 'followups'

export function WorkflowEngineView() {
  return (
    <ErrorBoundary>
      <WorkflowEngineViewInner />
    </ErrorBoundary>
  )
}

function WorkflowEngineViewInner() {
  const { selectedRepo } = useAccountStore()
  const { fetchInstance } = useWorkflowEngineStore()
  const [view, setView] = useState<View>('list')
  const [activeInstance, setActiveInstance] = useState<WorkflowInstance | null>(null)

  const repoFullName = selectedRepo ? `${selectedRepo.owner.login}/${selectedRepo.name}` : ''

  const goToDetail = (inst: WorkflowInstance) => {
    setActiveInstance(inst)
    setView('detail')
  }

  const goToGate = () => setView('gate')

  const goToList = () => {
    setActiveInstance(null)
    setView('list')
  }

  const handleStarted = async (instanceId: number) => {
    await fetchInstance(instanceId)
    const inst: WorkflowInstance = {
      id: instanceId,
      template_id: 0,
      template_name: '',
      repo: repoFullName,
      status: 'running',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    setActiveInstance(inst)
    setView('detail')
  }

  switch (view) {
    case 'config':
      return (
        <RunConfigPanel
          repo={repoFullName}
          onClose={() => setView('list')}
          onStarted={handleStarted}
        />
      )
    case 'detail':
      if (!activeInstance) { setView('list'); return null }
      return (
        <WorkflowRunDetail
          instance={activeInstance}
          onBack={goToList}
          onOpenGate={goToGate}
        />
      )
    case 'gate':
      if (!activeInstance) { setView('list'); return null }
      return (
        <GateView
          instance={activeInstance}
          onBack={() => setView('detail')}
        />
      )
    case 'domains':
      return <ExpertDomainManager onClose={() => setView('list')} />
    case 'followups':
      return <FollowUpTracker repo={repoFullName} onClose={() => setView('list')} />
    default:
      return (
        <WorkflowRunList
          onSelectInstance={goToDetail}
          onNewRun={() => setView('config')}
          onOpenDomains={() => setView('domains')}
          onOpenFollowups={() => setView('followups')}
        />
      )
  }
}
