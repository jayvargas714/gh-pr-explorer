import { useUIStore } from '../../stores/useUIStore'
import { useQueueStore } from '../../stores/useQueueStore'
import { Button } from '../common/Button'
import { Badge } from '../common/Badge'

export function Header() {
  const { darkMode, toggleTheme, toggleQueuePanel, toggleHistoryPanel } = useUIStore()
  const queueCount = useQueueStore((state) => state.getQueueCount())

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
          title="Merge Queue"
        >
          <span className="mx-icon">📋</span>
          {queueCount > 0 && (
            <Badge variant="info" size="sm">
              {queueCount}
            </Badge>
          )}
        </Button>

        {/* History Toggle */}
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleHistoryPanel}
          className="mx-header__action"
          title="Review History"
        >
          <span className="mx-icon">🕒</span>
        </Button>

        {/* Theme Toggle */}
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleTheme}
          className="mx-header__action"
          title={`Switch to ${darkMode ? 'light' : 'dark'} mode`}
        >
          <span className="mx-icon">{darkMode ? '☀️' : '🌙'}</span>
        </Button>
      </div>
    </header>
  )
}
