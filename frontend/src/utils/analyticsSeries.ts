/**
 * Pure data transforms for the daily analytics rollup.
 * No React/DOM imports — must bundle standalone for node.
 */

import { DailyRawKey, DailySeries, DailyTotals, DailyPerson } from '../api/types'

// ============================================================================
// Window / date range
// ============================================================================

export type WindowPreset = 'all' | '1d' | '1w' | '1m' | '3m' | '6m' | '1y' | 'custom'

export interface AnalyticsWindow {
  preset: WindowPreset
  from: string
  to: string
}

export interface DateRange {
  from: string | null
  to: string
}

export const WINDOW_PRESETS: { value: WindowPreset; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
  { value: '6m', label: '6M' },
  { value: '1y', label: '1Y' },
]

/**
 * Format a Date's UTC fields as 'YYYY-MM-DD'.
 */
export function utcDateString(d: Date): string {
  const y = d.getUTCFullYear()
  const m = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/**
 * Subtract `days` calendar days (UTC) from a 'YYYY-MM-DD' string.
 */
export function subtractDaysUTC(day: string, days: number): string {
  const [y, m, d] = day.split('-').map(Number)
  return utcDateString(new Date(Date.UTC(y, m - 1, d - days)))
}

/**
 * Subtract `months` calendar months (UTC) from a 'YYYY-MM-DD' string,
 * clamping the day-of-month to the target month's last day.
 */
export function subtractMonthsUTC(day: string, months: number): string {
  const [y, m, d] = day.split('-').map(Number)
  const totalMonths = y * 12 + (m - 1) - months
  const targetYear = Math.floor(totalMonths / 12)
  const targetMonth = ((totalMonths % 12) + 12) % 12
  const lastDayOfTargetMonth = new Date(Date.UTC(targetYear, targetMonth + 1, 0)).getUTCDate()
  const clampedDay = Math.min(d, lastDayOfTargetMonth)
  return utcDateString(new Date(Date.UTC(targetYear, targetMonth, clampedDay)))
}

/**
 * Validate a custom date range. Returns an error message, or null when valid.
 */
export function validateCustomRange(from: string, to: string, today: string): string | null {
  if (!from || !to) return 'Pick both dates'
  if (from > to) return 'Begin must be on or before end'
  if (to > today) return 'End cannot be in the future'
  return null
}

/**
 * Resolve an AnalyticsWindow into a concrete { from, to } range.
 * Returns null when the window is an invalid custom range.
 */
export function windowToRange(w: AnalyticsWindow, now: Date = new Date()): DateRange | null {
  const to = utcDateString(now)
  switch (w.preset) {
    case 'all':
      return { from: null, to }
    case '1d':
      return { from: to, to }
    case '1w':
      return { from: subtractDaysUTC(to, 6), to }
    case '1m':
      return { from: subtractMonthsUTC(to, 1), to }
    case '3m':
      return { from: subtractMonthsUTC(to, 3), to }
    case '6m':
      return { from: subtractMonthsUTC(to, 6), to }
    case '1y':
      return { from: subtractMonthsUTC(to, 12), to }
    case 'custom':
      return validateCustomRange(w.from, w.to, to) === null ? { from: w.from, to: w.to } : null
  }
}

// ============================================================================
// Metrics
// ============================================================================

export type MetricKey =
  | 'prs_created'
  | 'prs_merged'
  | 'prs_closed'
  | 'reviews'
  | 'approvals'
  | 'changes_requested'
  | 'comments'
  | 'additions'
  | 'deletions'
  | 'commits'
  | 'avg_merge_hours'
  | 'avg_review_rounds'

export const METRIC_LABELS: Record<MetricKey, string> = {
  prs_created: 'PRs created',
  prs_merged: 'merges',
  prs_closed: 'closed',
  reviews: 'reviews',
  approvals: 'approvals',
  changes_requested: 'changes requested',
  comments: 'comments',
  additions: 'lines added',
  deletions: 'lines deleted',
  commits: 'commits',
  avg_merge_hours: 'avg merge time',
  avg_review_rounds: 'avg review rounds',
}

export const METRIC_OPTIONS: { value: MetricKey; label: string }[] = (
  Object.keys(METRIC_LABELS) as MetricKey[]
).map((value) => ({ value, label: METRIC_LABELS[value] }))

export const HOURS_METRICS: ReadonlySet<MetricKey> = new Set(['avg_merge_hours'])

/** Metrics rendered as a plain decimal (one fractional digit) rather than
 * hours or a K/M-suffixed count. */
export const RATIO_METRICS: ReadonlySet<MetricKey> = new Set(['avg_review_rounds'])

export type YMode = 'daily' | 'cumulative'

/**
 * Running total of a series.
 */
export function cumulative(values: number[]): number[] {
  let sum = 0
  return values.map((v) => (sum += v))
}

/**
 * Weighted average of sum/count series, day by day or as a running average.
 */
export function weightedAvgSeries(
  sum: number[],
  count: number[],
  mode: YMode
): (number | null)[] {
  if (mode === 'daily') {
    return sum.map((s, i) => (count[i] === 0 ? null : s / count[i]))
  }
  let runningSum = 0
  let runningCount = 0
  return sum.map((s, i) => {
    runningSum += s
    runningCount += count[i]
    return runningCount === 0 ? null : runningSum / runningCount
  })
}

/**
 * Resolve a metric to a plotted series for the given y-axis mode.
 */
export function metricSeries(s: DailySeries, metric: MetricKey, mode: YMode): (number | null)[] {
  if (metric === 'avg_merge_hours') {
    return weightedAvgSeries(s.merge_hours_sum, s.merge_hours_count, mode)
  }
  if (metric === 'avg_review_rounds') {
    return weightedAvgSeries(s.review_rounds_sum, s.review_rounds_count, mode)
  }
  const raw = s[metric as DailyRawKey]
  return mode === 'cumulative' ? cumulative(raw) : raw
}

// ============================================================================
// Series specs (person x metric)
// ============================================================================

export const TEAM_ID = '__team__'

export interface SeriesSpec {
  id: string
  label: string
  color: string
  personId: string
  metric: MetricKey
}

export function seriesId(personId: string, metric: MetricKey): string {
  return `${personId}::${metric}`
}

export function seriesLabel(personLabel: string, metric: MetricKey): string {
  return `${personLabel} · ${METRIC_LABELS[metric]}`
}

export const SERIES_PALETTE: readonly string[] = [
  '#00d4aa',
  '#ff6b6b',
  '#4ecdc4',
  '#ffe66d',
  '#a29bfe',
  '#fd79a8',
  '#fdcb6e',
  '#6c5ce7',
  '#00b894',
  '#e17055',
  '#74b9ff',
  '#fab1a0',
  '#f97316',
  '#22d3ee',
  '#a3e635',
  '#e879f9',
]

export function seriesColor(index: number, palette: readonly string[] = SERIES_PALETTE): string {
  return palette[index % palette.length]
}

const defaultPersonLabel = (id: string): string => (id === TEAM_ID ? 'Team' : id)

export function buildSeriesSpecs(
  people: string[],
  metrics: MetricKey[],
  personLabel: (id: string) => string = defaultPersonLabel
): SeriesSpec[] {
  const specs: SeriesSpec[] = []
  let flatIndex = 0
  for (const personId of people) {
    for (const metric of metrics) {
      specs.push({
        id: seriesId(personId, metric),
        label: seriesLabel(personLabel(personId), metric),
        color: seriesColor(flatIndex),
        personId,
        metric,
      })
      flatIndex++
    }
  }
  return specs
}

// ============================================================================
// Chart rows / ticks
// ============================================================================

export type ChartRow = { day: string } & Record<string, number | null>

export function toChartRows(
  days: string[],
  columns: Record<string, (number | null)[]>
): ChartRow[] {
  const keys = Object.keys(columns)
  return days.map((day, i) => {
    const row = { day } as ChartRow
    for (const key of keys) {
      row[key] = columns[key][i]
    }
    return row
  })
}

const MONTH_ABBR = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

/**
 * Format a 'YYYY-MM-DD' day string for an x-axis tick, based on the chart's span.
 * Parses the string's parts directly — never goes through Date locale formatting.
 */
export function formatDayTick(day: string, spanDays: number): string {
  const [yStr, mStr, dStr] = day.split('-')
  const month = Number(mStr)
  const dayNum = Number(dStr)
  if (spanDays <= 92) {
    return `${month}/${dayNum}`
  }
  const monthAbbr = MONTH_ABBR[month - 1]
  if (spanDays <= 400) {
    return `${monthAbbr} ${dayNum}`
  }
  return `${monthAbbr} ${yStr.slice(-2)}`
}

export function xTickProps(nDays: number): {
  interval: number | 'preserveStartEnd'
  minTickGap: number
} {
  if (nDays <= 14) {
    return { interval: 0, minTickGap: 0 }
  }
  return { interval: 'preserveStartEnd', minTickGap: 28 }
}

// ============================================================================
// Stats table
// ============================================================================

export interface StatsRow {
  id: string
  login: string
  avatar_url: string | null
  prs_created: number
  prs_merged: number
  prs_closed: number
  merge_rate: number | null
  reviews: number
  approvals: number
  changes_requested: number
  additions: number
  deletions: number
  commits: number
  avg_merge_hours: number | null
  avg_review_rounds: number | null
}

function statsRowFromTotals(id: string, login: string, avatar_url: string | null, totals: DailyTotals): StatsRow {
  return {
    id,
    login,
    avatar_url,
    prs_created: totals.prs_created,
    prs_merged: totals.prs_merged,
    prs_closed: totals.prs_closed,
    merge_rate: totals.merge_rate,
    reviews: totals.reviews,
    approvals: totals.approvals,
    changes_requested: totals.changes_requested,
    additions: totals.additions,
    deletions: totals.deletions,
    commits: totals.commits,
    avg_merge_hours: totals.avg_merge_hours,
    avg_review_rounds: totals.avg_review_rounds,
  }
}

export function toStatsRows(people: DailyPerson[]): StatsRow[] {
  return people.map((p) => statsRowFromTotals(p.login, p.login, p.avatar_url ?? null, p.totals))
}

export function teamStatsRow(team: { series: DailySeries; totals: DailyTotals }): StatsRow {
  return statsRowFromTotals(TEAM_ID, 'Team', null, team.totals)
}

export function sortStatsRows(rows: StatsRow[], key: string, dir: 'asc' | 'desc'): StatsRow[] {
  const sign = dir === 'asc' ? 1 : -1
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const av = (a.row as unknown as Record<string, unknown>)[key]
      const bv = (b.row as unknown as Record<string, unknown>)[key]

      if (key === 'login') {
        const cmp = (av as string).localeCompare(bv as string)
        return cmp !== 0 ? cmp * sign : a.index - b.index
      }

      const aNull = av === null || av === undefined
      const bNull = bv === null || bv === undefined
      if (aNull && bNull) return a.index - b.index
      if (aNull) return 1
      if (bNull) return -1

      const cmp = (av as number) - (bv as number)
      return cmp !== 0 ? cmp * sign : a.index - b.index
    })
    .map((x) => x.row)
}

// ============================================================================
// Team activity summary
// ============================================================================

export interface TeamActivitySummary {
  totalCommits: number
  avgCommitsPerDay: number
  additions: number
  deletions: number
  peakDay: string | null
  peakCommits: number
  prsMerged: number
}

function sum(values: number[]): number {
  return values.reduce((a, b) => a + b, 0)
}

export function summarizeTeam(days: string[], team: DailySeries): TeamActivitySummary {
  const totalCommits = sum(team.commits)
  let peakDay: string | null = null
  let peakCommits = 0
  for (let i = 0; i < days.length; i++) {
    const c = team.commits[i] ?? 0
    if (c > peakCommits) {
      peakDay = days[i]
      peakCommits = c
    }
  }
  return {
    totalCommits,
    avgCommitsPerDay: days.length === 0 ? 0 : totalCommits / days.length,
    additions: sum(team.additions),
    deletions: sum(team.deletions),
    peakDay,
    peakCommits,
    prsMerged: sum(team.prs_merged),
  }
}

export const MAX_SERIES = 16
