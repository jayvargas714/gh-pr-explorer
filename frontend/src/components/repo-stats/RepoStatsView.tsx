import { useEffect, useState, useMemo } from 'react'
import { useRepoStatsStore } from '../../stores/useRepoStatsStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchRepoStats, fetchLOC, fetchCachedLOC } from '../../api/repoStats'
import { CacheTimestamp } from '../common/CacheTimestamp'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { InfoTooltip } from '../common/InfoTooltip'
import { formatNumber } from '../../utils/formatters'

// ============================================================================
// Language color map
// ============================================================================

const LANGUAGE_COLORS: Record<string, string> = {
  TypeScript: '#3178c6',
  JavaScript: '#f1e05a',
  Python: '#3572A5',
  Rust: '#dea584',
  Go: '#00ADD8',
  Java: '#b07219',
  'C++': '#f34b7d',
  C: '#555555',
  'C#': '#178600',
  Ruby: '#701516',
  PHP: '#4F5D95',
  Swift: '#F05138',
  Kotlin: '#A97BFF',
  Scala: '#c22d40',
  Shell: '#89e051',
  HTML: '#e34c26',
  CSS: '#563d7c',
  SCSS: '#c6538c',
  Vue: '#41b883',
  Svelte: '#ff3e00',
  Dart: '#00B4AB',
  R: '#198CE7',
  MATLAB: '#e16737',
  Julia: '#a270ba',
  Haskell: '#5e5086',
  Elixir: '#6e4a7e',
  Clojure: '#db5855',
  Erlang: '#B83998',
  Lua: '#000080',
  Perl: '#0298c3',
  Groovy: '#e69f56',
  PowerShell: '#012456',
  Makefile: '#427819',
  Dockerfile: '#384d54',
  YAML: '#cb171e',
  JSON: '#292929',
  Markdown: '#083fa1',
  Terraform: '#7B42BC',
  Nix: '#7e7eff',
}

const FALLBACK_COLORS = [
  '#00d4aa', '#ff6b6b', '#4ecdc4', '#ffe66d', '#a29bfe',
  '#fd79a8', '#6c5ce7', '#00b894', '#e17055', '#74b9ff',
]

function getLanguageColor(name: string, index: number): string {
  return LANGUAGE_COLORS[name] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

function formatAge(days: number): string {
  const years = Math.floor(days / 365)
  const months = Math.floor((days % 365) / 30)
  if (years > 0 && months > 0) return `${years}y ${months}mo`
  if (years > 0) return `${years}y`
  if (months > 0) return `${months}mo`
  return `${days}d`
}

function formatBytes(bytes: number): string {
  const kb = bytes * 1024
  if (kb >= 1024 * 1024 * 1024) return `${(kb / (1024 * 1024 * 1024)).toFixed(1)} GB`
  if (kb >= 1024 * 1024) return `${(kb / (1024 * 1024)).toFixed(1)} MB`
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} KB`
  return `${kb} B`
}

// ============================================================================
// Component
// ============================================================================

export function RepoStatsView() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const {
    repoStats,
    loading,
    error,
    locResult,
    locLastUpdated,
    locLoading,
    locError,
    cacheMeta,
    setRepoStats,
    setLoading,
    setError,
    setLOCResult,
    setLOCLoading,
    setLOCError,
    setLOCLastUpdated,
    setCacheMeta,
    reset,
  } = useRepoStatsStore()

  const [showAllExtensions, setShowAllExtensions] = useState(false)
  const [extSortBy, setExtSortBy] = useState<'extension' | 'count'>('count')
  const [extSortDir, setExtSortDir] = useState<'asc' | 'desc'>('desc')

  useEffect(() => {
    if (selectedRepo) {
      reset()
      loadStats()
      loadCachedLOC()
    }
  }, [selectedRepo])

  const loadStats = async () => {
    if (!selectedRepo) return
    try {
      setLoading(true)
      setError(null)
      const response = await fetchRepoStats(selectedRepo.owner.login, selectedRepo.name)
      setRepoStats(response)
      setCacheMeta({
        last_updated: response.last_updated,
        cached: response.cached,
        stale: response.stale,
        refreshing: response.refreshing,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load repo stats')
    } finally {
      setLoading(false)
    }
  }

  const loadCachedLOC = async () => {
    if (!selectedRepo) return
    try {
      const response = await fetchCachedLOC(selectedRepo.owner.login, selectedRepo.name)
      setLOCResult(response)
      setLOCLastUpdated(response.last_updated)
    } catch {
      // 404 = no cached data, that's fine — user can click Calculate
    }
  }

  const handleCalculateLOC = async () => {
    if (!selectedRepo) return
    try {
      setLOCLoading(true)
      setLOCError(null)
      const response = await fetchLOC(selectedRepo.owner.login, selectedRepo.name)
      setLOCResult(response)
      setLOCLastUpdated(response.last_updated)
    } catch (err) {
      setLOCError(err instanceof Error ? err.message : 'Failed to calculate LOC')
    } finally {
      setLOCLoading(false)
    }
  }

  const handleRecalculateLOC = async () => {
    setLOCResult(null)
    await handleCalculateLOC()
  }

  const sortedExtensions = useMemo(() => {
    if (!repoStats) return []
    const sorted = [...repoStats.files_by_extension].sort((a, b) => {
      if (extSortBy === 'extension') {
        const cmp = a.extension.localeCompare(b.extension)
        return extSortDir === 'asc' ? cmp : -cmp
      }
      // sort by count
      return extSortDir === 'asc' ? a.count - b.count : b.count - a.count
    })
    return showAllExtensions ? sorted : sorted.slice(0, 20)
  }, [repoStats, extSortBy, extSortDir, showAllExtensions])

  const toggleExtSort = (col: 'extension' | 'count') => {
    if (col === extSortBy) {
      setExtSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setExtSortBy(col)
      setExtSortDir('desc')
    }
  }

  const sortIndicator = (col: 'extension' | 'count') => {
    if (extSortBy !== col) return ' ⇅'
    return extSortDir === 'asc' ? ' ▲' : ' ▼'
  }

  if (loading) {
    return (
      <div className="mx-analytics__loading">
        <Spinner size="lg" />
        <p>Loading repo stats...</p>
      </div>
    )
  }

  if (error) {
    return <Alert variant="error">{error}</Alert>
  }

  if (!repoStats) return null

  const { overview, code, prs, languages, files_by_extension } = repoStats
  const hasMoreExtensions = files_by_extension.length > 20

  return (
    <div className="mx-repo-stats">
      <CacheTimestamp
        lastUpdated={cacheMeta.last_updated}
        stale={cacheMeta.stale}
        refreshing={cacheMeta.refreshing}
      />

      {/* Overview Card */}
      <div className="mx-repo-overview">
        <div className="mx-repo-overview__main">
          <h2 className="mx-repo-overview__name">{overview.full_name}</h2>
          {overview.description && (
            <p className="mx-repo-overview__description">{overview.description}</p>
          )}
          <div className="mx-repo-overview__badges">
            <span className="mx-repo-overview__badge">
              {overview.default_branch}
            </span>
            {overview.license && (
              <span className="mx-repo-overview__badge">
                {overview.license}
              </span>
            )}
            <span className="mx-repo-overview__badge">
              {formatAge(overview.age_days)} old
            </span>
            <span className="mx-repo-overview__badge">
              {formatBytes(overview.size_kb)}
            </span>
          </div>
          <div className="mx-repo-overview__counters">
            <div className="mx-repo-overview__counter">
              <span className="mx-repo-overview__counter-value">
                {formatNumber(overview.stars)}
              </span>
              Stars
            </div>
            <div className="mx-repo-overview__counter">
              <span className="mx-repo-overview__counter-value">
                {formatNumber(overview.forks)}
              </span>
              Forks
            </div>
            <div className="mx-repo-overview__counter">
              <span className="mx-repo-overview__counter-value">
                {formatNumber(overview.watchers)}
              </span>
              Watchers
            </div>
            <div className="mx-repo-overview__counter">
              <span className="mx-repo-overview__counter-value">
                {formatNumber(overview.open_issues)}
              </span>
              Open Issues
            </div>
          </div>
        </div>
      </div>

      {/* Stat Cards Row 1 */}
      <div className="mx-stat-cards">
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Total Commits</span>
          <span className="mx-stat-card__value">{formatNumber(code.total_commits)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Total Files</span>
          <span className="mx-stat-card__value">{formatNumber(code.total_files)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Contributors</span>
          <span className="mx-stat-card__value">{formatNumber(code.total_contributors)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Branches</span>
          <span className="mx-stat-card__value">{formatNumber(code.total_branches)}</span>
        </div>
      </div>

      {/* Stat Cards Row 2 */}
      <div className="mx-stat-cards">
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Open PRs</span>
          <span className="mx-stat-card__value">{formatNumber(prs.open)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">All-time Opened</span>
          <span className="mx-stat-card__value">{formatNumber(prs.total_all_time)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">All-time Closed</span>
          <span className="mx-stat-card__value">{formatNumber(prs.closed)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">All-time Merged</span>
          <span className="mx-stat-card__value">{formatNumber(prs.merged)}</span>
        </div>
      </div>

      {/* Language Breakdown */}
      {languages.length > 0 && (
        <>
          <h3 className="mx-repo-stats__section-title">Language Breakdown</h3>
          <div className="mx-language-bar">
            {languages.map((lang, i) => (
              <div
                key={lang.name}
                className="mx-language-bar__segment"
                style={{
                  width: `${lang.percentage}%`,
                  backgroundColor: getLanguageColor(lang.name, i),
                }}
                title={`${lang.name}: ${lang.percentage.toFixed(1)}%`}
              />
            ))}
          </div>
          <div className="mx-language-legend">
            {languages.map((lang, i) => (
              <div key={lang.name} className="mx-language-legend__item">
                <span
                  className="mx-language-legend__swatch"
                  style={{ backgroundColor: getLanguageColor(lang.name, i) }}
                />
                <span className="mx-language-legend__name">{lang.name}</span>
                <span className="mx-language-legend__pct">{lang.percentage.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Files by Extension */}
      {files_by_extension.length > 0 && (
        <>
          <h3 className="mx-repo-stats__section-title">Files by Extension<InfoTooltip text="File count grouped by extension from the repository's default branch. Click column headers to sort." /></h3>
          <table className="mx-ext-table">
            <thead>
              <tr>
                <th onClick={() => toggleExtSort('extension')} title="File extension (e.g. .ts, .py)">
                  Extension{sortIndicator('extension')}
                </th>
                <th onClick={() => toggleExtSort('count')} title="Number of files with this extension">
                  Count{sortIndicator('count')}
                </th>
                <th title="Percentage of total files">%</th>
              </tr>
            </thead>
            <tbody>
              {sortedExtensions.map((ext) => (
                <tr key={ext.extension}>
                  <td>{ext.extension || '(no ext)'}</td>
                  <td>{formatNumber(ext.count)}</td>
                  <td>{ext.percentage.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasMoreExtensions && (
            <button
              className="mx-show-all-toggle"
              onClick={() => setShowAllExtensions((v) => !v)}
            >
              {showAllExtensions
                ? `Show fewer`
                : `Show all ${files_by_extension.length} extensions`}
            </button>
          )}
        </>
      )}

      {/* LOC Section */}
      <div className="mx-loc-section">
        <h3 className="mx-repo-stats__section-title">Lines of Code<InfoTooltip text="Non-whitespace line counts per language via shallow clone. Detects common comment syntaxes (// # /* */ <!-- -->) for supported languages." /></h3>

        {!locResult && !locLoading && !locError && (
          <button className="mx-loc-trigger" onClick={handleCalculateLOC}>
            <span className="mx-loc-trigger__icon">📊</span>
            <div className="mx-loc-trigger__text">
              <span className="mx-loc-trigger__title">Calculate Lines of Code</span>
              <span className="mx-loc-trigger__hint">
                Runs cloc on the repository — may take a few seconds
              </span>
            </div>
          </button>
        )}

        {locLoading && (
          <div className="mx-analytics__loading">
            <Spinner size="md" />
            <p>Counting lines of code...</p>
          </div>
        )}

        {locError && <Alert variant="error">{locError}</Alert>}

        {locResult && !locLoading && (
          <>
            {locLastUpdated && (
              <CacheTimestamp lastUpdated={locLastUpdated} stale={false} refreshing={false} />
            )}
            <table className="mx-loc-table">
              <thead>
                <tr>
                  <th title="Programming language detected from file extension">Language</th>
                  <th title="Number of source files for this language">Files</th>
                  <th title="Empty lines (whitespace only)">Blank</th>
                  <th title="Lines identified as comments (// # /* */ <!-- --> etc.)">Comment</th>
                  <th title="Non-blank, non-comment lines of code">Code</th>
                </tr>
              </thead>
              <tbody>
                {locResult.loc.map((entry) => (
                  <tr key={entry.language}>
                    <td>{entry.language}</td>
                    <td>{formatNumber(entry.files)}</td>
                    <td>{formatNumber(entry.blank)}</td>
                    <td>{formatNumber(entry.comment)}</td>
                    <td>{formatNumber(entry.code)}</td>
                  </tr>
                ))}
                <tr className="mx-loc-totals">
                  <td>Total</td>
                  <td>{formatNumber(locResult.totals.files)}</td>
                  <td>{formatNumber(locResult.totals.blank)}</td>
                  <td>{formatNumber(locResult.totals.comment)}</td>
                  <td>{formatNumber(locResult.totals.code)}</td>
                </tr>
              </tbody>
            </table>
            <button className="mx-loc-recalculate" onClick={handleRecalculateLOC}>
              Recalculate
            </button>
          </>
        )}
      </div>
    </div>
  )
}
