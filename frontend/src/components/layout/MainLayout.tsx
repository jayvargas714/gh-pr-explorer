import { ReactNode } from 'react'
import { Header } from './Header'
import { ViewTabs } from './ViewTabs'
import { Footer } from './Footer'
import { WelcomeSection } from './WelcomeSection'
import { useAccountStore } from '../../stores/useAccountStore'

interface MainLayoutProps {
  children: ReactNode
}

export function MainLayout({ children }: MainLayoutProps) {
  const { selectedAccount, selectedRepo } = useAccountStore()

  return (
    <div className="mx-layout">
      <Header />

      <main className="mx-main">
        {!selectedAccount ? (
          <WelcomeSection />
        ) : !selectedRepo ? (
          <div className="mx-empty-state">
            <h2>Select a Repository</h2>
            <p>Choose a repository from the dropdown above to view pull requests</p>
          </div>
        ) : (
          <>
            <ViewTabs />
            <div className="mx-content">{children}</div>
          </>
        )}
      </main>

      <Footer />
    </div>
  )
}
