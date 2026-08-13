import { useState } from 'react'
import { useUIStore } from '../../stores/useUIStore'
import { useQueueStore } from '../../stores/useQueueStore'
import { describeCriteria, useAutoVerdictStore } from '../../stores/useAutoVerdictStore'
import { AutoVerdictConfigModal } from '../autoVerdict/AutoVerdictConfigModal'
import { Button } from '../common/Button'
import { Badge } from '../common/Badge'

export function Header() {
  const { darkMode, toggleTheme, toggleQueuePanel, toggleHistoryPanel, toggleSwimlaneBoard } = useUIStore()
  const queueCount = useQueueStore((state) => state.getQueueCount())
  const autoVerdictConfig = useAutoVerdictStore((state) => state.config)
  const [showAutoVerdictConfig, setShowAutoVerdictConfig] = useState(false)

  return (
    <header className="mx-header">
      <div className="mx-header__left">
        <div className="mx-header__logo">
          <span className="mx-logo-icon">{'>'}_</span>
          <h1 className="mx-logo-text">GitHub PR Explorer</h1>
        </div>
      </div>

      <div className="mx-header__right">
        {/* Queue Toggle */}
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleQueuePanel}
          className="mx-header__action"
          data-tooltip="Merge Queue"
        >
          <span className="mx-icon">📋</span>
          {queueCount > 0 && (
            <Badge variant="info" size="sm">
              {queueCount}
            </Badge>
          )}
        </Button>

        {/* Swimlane Board Toggle */}
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleSwimlaneBoard}
          className="mx-header__action"
          data-tooltip="Swimlane Board"
        >
          <span className="mx-icon">📊</span>
        </Button>

        {/* Auto Verdict Criteria */}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowAutoVerdictConfig(true)}
          className="mx-header__action"
          data-tooltip={`Auto Verdict Criteria — ${describeCriteria(autoVerdictConfig)}`}
        >
          <span className="mx-icon">🤖</span>
          {autoVerdictConfig.enabled && (
            <Badge variant="success" size="sm">
              on
            </Badge>
          )}
        </Button>

        {/* History Toggle */}
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleHistoryPanel}
          className="mx-header__action"
          data-tooltip="Review History"
        >
          <span className="mx-icon">🕒</span>
        </Button>

        {/* Theme Toggle */}
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleTheme}
          className="mx-header__action"
          data-tooltip={`Switch to ${darkMode ? 'light' : 'dark'} mode`}
        >
          <span className="mx-icon">{darkMode ? '☀️' : '🌙'}</span>
        </Button>
      </div>

      {showAutoVerdictConfig && (
        <AutoVerdictConfigModal onClose={() => setShowAutoVerdictConfig(false)} />
      )}
    </header>
  )
}
