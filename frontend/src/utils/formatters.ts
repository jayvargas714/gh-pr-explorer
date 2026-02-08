/**
 * Utility functions for formatting dates, numbers, and durations
 */

/**
 * Format a date string to relative time (e.g., "2 days ago")
 */
export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)
  const diffWeek = Math.floor(diffDay / 7)
  const diffMonth = Math.floor(diffDay / 30)
  const diffYear = Math.floor(diffDay / 365)

  if (diffSec < 60) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHour < 24) return `${diffHour}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  if (diffWeek < 4) return `${diffWeek}w ago`
  if (diffMonth < 12) return `${diffMonth}mo ago`
  return `${diffYear}y ago`
}

/**
 * Format a date string to short date (e.g., "Jan 15, 2024")
 */
export function formatShortDate(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

/**
 * Format a date string to full date and time
 */
export function formatFullDateTime(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

/**
 * Format a number with K/M suffixes (e.g., 1500 -> "1.5K")
 */
export function formatNumber(num: number): string {
  if (num >= 1_000_000) {
    return (num / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M'
  }
  if (num >= 1_000) {
    return (num / 1_000).toFixed(1).replace(/\.0$/, '') + 'K'
  }
  return num.toString()
}

/**
 * Format duration in seconds to human-readable string (e.g., "3m 45s")
 */
export function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}s`
  }
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes < 60) {
    return remainingSeconds > 0
      ? `${minutes}m ${remainingSeconds}s`
      : `${minutes}m`
  }
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  if (hours < 24) {
    return remainingMinutes > 0
      ? `${hours}h ${remainingMinutes}m`
      : `${hours}h`
  }
  const days = Math.floor(hours / 24)
  const remainingHours = hours % 24
  return remainingHours > 0
    ? `${days}d ${remainingHours}h`
    : `${days}d`
}

/**
 * Format hours to human-readable string (e.g., "2d 5h")
 */
export function formatHours(hours: number | null): string {
  if (hours === null || hours === undefined) return 'N/A'
  if (hours < 1) return `${Math.round(hours * 60)}m`
  if (hours < 24) return `${Math.round(hours * 10) / 10}h`
  const days = Math.floor(hours / 24)
  const remainingHours = Math.round(hours % 24)
  return remainingHours > 0 ? `${days}d ${remainingHours}h` : `${days}d`
}

/**
 * Format percentage (e.g., 0.873 -> "87.3%")
 */
export function formatPercentage(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

/**
 * Truncate text to max length with ellipsis
 */
export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength) + '...'
}

/**
 * Get CSS class for review score badge
 */
export function getScoreClass(score: number | null): string {
  if (score === null || score === undefined) return 'score-none'
  if (score >= 7) return 'score-good'
  if (score >= 4) return 'score-moderate'
  return 'score-poor'
}

/**
 * Get CSS class for PR state
 */
export function getPRStateClass(state: string): string {
  switch (state?.toLowerCase()) {
    case 'open':
      return 'pr-state-open'
    case 'merged':
      return 'pr-state-merged'
    case 'closed':
      return 'pr-state-closed'
    default:
      return 'pr-state-unknown'
  }
}

/**
 * Get CSS class for workflow conclusion
 */
export function getWorkflowConclusionClass(conclusion: string | null): string {
  switch (conclusion?.toLowerCase()) {
    case 'success':
      return 'wf-success'
    case 'failure':
      return 'wf-failure'
    case 'cancelled':
      return 'wf-cancelled'
    case 'skipped':
      return 'wf-skipped'
    default:
      return 'wf-in-progress'
  }
}

/**
 * Calculate percentage with division by zero handling
 */
export function calculatePercentage(numerator: number, denominator: number): number {
  if (denominator === 0) return 0
  return (numerator / denominator) * 100
}
