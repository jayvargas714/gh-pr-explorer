import { useEffect } from 'react'
import { MainLayout } from './components/layout/MainLayout'
import { AccountSelector } from './components/account/AccountSelector'
import { RepoSelector } from './components/account/RepoSelector'
import { FilterPanel } from './components/filters/FilterPanel'
import { PRList } from './components/prs/PRList'
import { AnalyticsView } from './components/analytics/AnalyticsView'
import { useAccountStore } from './stores/useAccountStore'
import { useUIStore } from './stores/useUIStore'

function App() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const activeView = useUIStore((state) => state.activeView)

  useEffect(() => {
    // Check for saved theme preference or default to dark
    const savedTheme = localStorage.getItem('theme')
    if (savedTheme === 'light') {
      document.documentElement.classList.add('matrix-light')
    }
  }, [])

  const renderView = () => {
    if (!selectedRepo) return null

    switch (activeView) {
      case 'prs':
        return <PRList />
      case 'analytics':
        return <AnalyticsView />
      case 'workflows':
        return (
          <div className="mx-placeholder">
            <p>Workflows view - Phase 7</p>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <MainLayout>
      <AccountSelector />
      <RepoSelector />

      {selectedRepo && (
        <>
          <FilterPanel />
          {renderView()}
        </>
      )}
    </MainLayout>
  )
}

export default App
