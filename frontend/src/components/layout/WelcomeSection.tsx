export function WelcomeSection() {
  return (
    <div className="mx-welcome">
      <div className="mx-welcome__content">
        <h1 className="mx-welcome__title">Welcome to GitHub PR Explorer</h1>
        <p className="mx-welcome__subtitle">
          Browse, filter, and analyze pull requests across your repositories
        </p>

        <div className="mx-welcome__features">
          <div className="mx-welcome__feature">
            <span className="mx-welcome__feature-icon">🔍</span>
            <h3>Advanced Filtering</h3>
            <p>40+ filter options including labels, reviewers, dates, and more</p>
          </div>

          <div className="mx-welcome__feature">
            <span className="mx-welcome__feature-icon">📊</span>
            <h3>Analytics Dashboard</h3>
            <p>Developer stats, PR lifecycle metrics, and code activity insights</p>
          </div>

          <div className="mx-welcome__feature">
            <span className="mx-welcome__feature-icon">⚙️</span>
            <h3>CI/CD Monitoring</h3>
            <p>Track workflow runs, pass rates, and failure trends</p>
          </div>

          <div className="mx-welcome__feature">
            <span className="mx-welcome__feature-icon">🤖</span>
            <h3>Code Reviews</h3>
            <p>AI-powered code reviews with Claude integration</p>
          </div>
        </div>

        <div className="mx-welcome__instructions">
          <p>
            <strong>Get started:</strong> Select an account or organization from the dropdown
            above
          </p>
        </div>
      </div>
    </div>
  )
}
