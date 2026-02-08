import { useEffect } from 'react'

function App() {
  useEffect(() => {
    // Check for saved theme preference or default to dark
    const savedTheme = localStorage.getItem('theme')
    if (savedTheme === 'light') {
      document.documentElement.classList.add('matrix-light')
    }
  }, [])

  return (
    <div className="app">
      <h1>GitHub PR Explorer</h1>
      <p>React + TypeScript + Matrix UI - Phase 0 Complete</p>
    </div>
  )
}

export default App
