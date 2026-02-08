import { ReactNode } from 'react'
import { Header } from './Header'
import { Footer } from './Footer'

interface MainLayoutProps {
  children: ReactNode
}

export function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="mx-layout">
      <Header />

      <main className="mx-main">
        {children}
      </main>

      <Footer />
    </div>
  )
}
