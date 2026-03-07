import { useState } from 'react'
import { WorkflowRunList } from './WorkflowRunList'
import { WorkflowRunDetail } from './WorkflowRunDetail'
import { GatePanel } from './GatePanel'
import type { WorkflowInstance } from '../../api/workflow-engine'

export function WorkflowEngineView() {
  const [selectedInstance, setSelectedInstance] = useState<WorkflowInstance | null>(null)
  const [showGate, setShowGate] = useState(false)

  if (selectedInstance) {
    return (
      <>
        <WorkflowRunDetail
          instance={selectedInstance}
          onBack={() => setSelectedInstance(null)}
          onOpenGate={() => setShowGate(true)}
        />
        {showGate && (
          <GatePanel
            instance={selectedInstance}
            onClose={() => setShowGate(false)}
          />
        )}
      </>
    )
  }

  return <WorkflowRunList onSelectInstance={setSelectedInstance} />
}
