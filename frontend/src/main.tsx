import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './styles/variables.css'
import './styles/global.css'
import './styles/components.css'
import './styles/layout.css'
import './styles/filters.css'
import './styles/prs.css'
import './styles/analytics.css'
import './styles/workflows.css'
import './styles/queue.css'
import './styles/reviews.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
