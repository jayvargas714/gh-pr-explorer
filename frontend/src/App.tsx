import { useEffect } from 'react'
import { MainLayout } from './components/layout/MainLayout'
import { AccountSelector } from './components/account/AccountSelector'
import { RepoSelector } from './components/account/RepoSelector'
import { FilterPanel } from './components/filters/FilterPanel'
import { useAccountStore } from './stores/useAccountStore'

function App() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)

  useEffect(() => {
    // Check for saved theme preference or default to dark
    const savedTheme = localStorage.getItem('theme')
    if (savedTheme === 'light') {
      document.documentElement.classList.add('matrix-light')
    }
  }, [])

  return (
    <MainLayout>
      <AccountSelector />
      <RepoSelector />

      {selectedRepo && (
        <>
          <FilterPanel />
          <div className="mx-placeholder">
            <p>Phase 4 Complete - Ready for Phase 5 (PR List)</p>
            <p>Selected: {selectedRepo.owner.login}/{selectedRepo.name}</p>
          </div>
        </>
      )}
    </MainLayout>
  )
}

export default App
