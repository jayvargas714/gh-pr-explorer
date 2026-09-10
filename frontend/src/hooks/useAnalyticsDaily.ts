import { useEffect, useRef } from 'react'
import { useAccountStore } from '../stores/useAccountStore'
import { useAnalyticsStore } from '../stores/useAnalyticsStore'
import { fetchAnalyticsDaily } from '../api/analytics'
import { usePolling } from './usePolling'
import { DateRange, utcDateString, validateCustomRange, windowToRange } from '../utils/analyticsSeries'

/**
 * Loads the daily analytics rollup for the selected repo/window/base and
 * keeps it fresh while the backend is still syncing.
 */
export function useAnalyticsDaily(): {
  range: DateRange | null
  rangeError: string | null
  isStale: boolean
} {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const window = useAnalyticsStore((state) => state.window)
  const base = useAnalyticsStore((state) => state.base)
  const daily = useAnalyticsStore((state) => state.daily)
  const dailyKey = useAnalyticsStore((state) => state.dailyKey)
  const setDaily = useAnalyticsStore((state) => state.setDaily)
  const setDailyLoading = useAnalyticsStore((state) => state.setDailyLoading)
  const setDailyError = useAnalyticsStore((state) => state.setDailyError)
  const resetForRepo = useAnalyticsStore((state) => state.resetForRepo)

  const requestId = useRef(0)
  const repoIdentity = selectedRepo ? `${selectedRepo.owner.login}/${selectedRepo.name}` : null
  const prevRepoIdentity = useRef(repoIdentity)

  const today = utcDateString(new Date())
  const rangeError = window.preset === 'custom' ? validateCustomRange(window.from, window.to, today) : null
  const range = windowToRange(window)

  const key = range && selectedRepo ? `${repoIdentity}|${range.from ?? ''}|${range.to}|${base}` : null

  const load = (silent: boolean) => {
    if (!key || !selectedRepo || !range) return
    const id = ++requestId.current
    if (!silent) setDailyLoading(true)
    fetchAnalyticsDaily(selectedRepo.owner.login, selectedRepo.name, {
      from: range.from,
      to: range.to,
      base,
    })
      .then((resp) => {
        if (id !== requestId.current) return
        setDaily(resp, key)
      })
      .catch((err) => {
        if (id !== requestId.current) return
        setDailyError(err instanceof Error ? err.message : 'Failed to load analytics')
      })
      .finally(() => {
        if (id !== requestId.current) return
        if (!silent) setDailyLoading(false)
      })
  }

  useEffect(() => {
    if (key && key !== dailyKey) load(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  useEffect(() => {
    if (prevRepoIdentity.current !== repoIdentity) {
      prevRepoIdentity.current = repoIdentity
      resetForRepo()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoIdentity])

  usePolling(() => load(true), 15000, daily?.syncing === true)

  return { range, rangeError, isStale: key !== dailyKey }
}
