import React from 'react'

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 200, padding: 32 }}>
          <div style={{ textAlign: 'center', maxWidth: 400 }}>
            <h3 style={{ margin: '0 0 8px' }}>Something went wrong</h3>
            <p style={{ margin: '0 0 16px', opacity: 0.7, fontSize: 14 }}>
              {this.state.error?.message || 'An unexpected error occurred'}
            </p>
            <button
              className="mx-button mx-button--primary mx-button--sm"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              Try Again
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
