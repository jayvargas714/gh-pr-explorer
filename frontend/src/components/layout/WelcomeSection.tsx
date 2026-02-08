import { Alert } from '../common/Alert'

export function WelcomeSection() {
  return (
    <div className="mx-welcome">
      <div className="mx-welcome__container">
        <h1 className="mx-welcome__title">Welcome to GitHub PR Explorer</h1>
        <p className="mx-welcome__subtitle">
          A powerful tool for browsing, filtering, and managing GitHub Pull Requests
        </p>

        <Alert variant="warning">
          <strong>GitHub CLI Required</strong>
          <p style={{ marginTop: '8px' }}>
            This application requires the GitHub CLI (`gh`) to be installed and authenticated.
          </p>
        </Alert>

        <div className="mx-welcome__steps">
          <h2>Getting Started</h2>

          <div className="mx-welcome__step">
            <div className="mx-welcome__step-number">1</div>
            <div className="mx-welcome__step-content">
              <h3>Install GitHub CLI</h3>
              <p>Visit <a href="https://cli.github.com" target="_blank" rel="noopener noreferrer">cli.github.com</a> to download and install the GitHub CLI.</p>
            </div>
          </div>

          <div className="mx-welcome__step">
            <div className="mx-welcome__step-number">2</div>
            <div className="mx-welcome__step-content">
              <h3>Authenticate</h3>
              <p>Run <code>gh auth login</code> in your terminal and follow the prompts to authenticate with GitHub.</p>
            </div>
          </div>

          <div className="mx-welcome__step">
            <div className="mx-welcome__step-number">3</div>
            <div className="mx-welcome__step-content">
              <h3>Refresh this page</h3>
              <p>Once authenticated, refresh this page to start exploring your Pull Requests.</p>
            </div>
          </div>
        </div>

        <div className="mx-welcome__features">
          <h2>Features</h2>
          <ul>
            <li>Browse PRs across personal accounts and organizations</li>
            <li>Advanced filtering with 40+ filter properties</li>
            <li>Developer analytics and contribution statistics</li>
            <li>CI/Workflow monitoring with pass rates and duration tracking</li>
            <li>Merge queue for organizing PRs to review</li>
            <li>Code review system with Claude CLI integration</li>
            <li>Review history with search and filters</li>
            <li>Dark/light theme support</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
