import { useEffect, useRef } from 'react'
import { getSetting } from '../api/settings'
import { useAccountStore } from '../stores/useAccountStore'
import { useFilterStore, debouncedSaveSettings } from '../stores/useFilterStore'

/**
 * Restores saved settings on mount (account, repo, filters)
 * and auto-saves filter/selection changes with 1s debounce.
 */
export function useSettingsPersistence() {
  const {
    accounts,
    accountsLoading,
    selectedAccount,
    selectedRepo,
    repos,
    reposLoading,
    setSelectedAccount,
    setSelectedRepo,
  } = useAccountStore()

  const filters = useFilterStore()
  const restoredRef = useRef(false)
  const pendingSettingsRef = useRef<any>(null)

  // Phase 1: Fetch saved settings on mount
  useEffect(() => {
    if (restoredRef.current) return
    getSetting('filter_settings')
      .then((data) => {
        if (data.value) {
          pendingSettingsRef.current = data.value
        }
      })
      .catch(() => {
        // No saved settings, that's fine
      })
  }, [])

  // Phase 2: Once accounts load, restore selected account
  useEffect(() => {
    if (restoredRef.current || accountsLoading || accounts.length === 0) return
    const saved = pendingSettingsRef.current
    if (!saved?.selectedAccountLogin) {
      restoredRef.current = true
      if (saved?.filters) {
        filters.restoreFilters(saved.filters)
      }
      return
    }

    const account = accounts.find((a) => a.login === saved.selectedAccountLogin)
    if (account) {
      setSelectedAccount(account)
    } else {
      restoredRef.current = true
    }
  }, [accounts, accountsLoading])

  // Phase 3: Once repos load after account selection, restore selected repo + filters
  useEffect(() => {
    if (restoredRef.current || reposLoading || repos.length === 0) return
    const saved = pendingSettingsRef.current
    if (!saved?.selectedRepoFullName) {
      restoredRef.current = true
      if (saved?.filters) {
        filters.restoreFilters(saved.filters)
      }
      return
    }

    const repo = repos.find(
      (r) => `${r.owner.login}/${r.name}` === saved.selectedRepoFullName
    )
    if (repo) {
      setSelectedRepo(repo)
      // Restore filters after repo selection so PRList re-fetches with them
      setTimeout(() => {
        if (saved.filters) {
          filters.restoreFilters(saved.filters)
        }
        restoredRef.current = true
      }, 50)
    } else {
      restoredRef.current = true
    }
  }, [repos, reposLoading])

  // Phase 4: Auto-save on filter/selection changes (1s debounce)
  const isFirstRender = useRef(true)
  useEffect(() => {
    // Skip saving on initial render and during restore
    if (isFirstRender.current) {
      isFirstRender.current = false
      return
    }
    if (filters._skipSave || !restoredRef.current) return

    const { setFilter, resetFilters, getActiveFiltersCount, restoreFilters, _skipSave, ...filterValues } = filters
    const accountLogin = selectedAccount?.login || null
    const repoFullName = selectedRepo
      ? `${selectedRepo.owner.login}/${selectedRepo.name}`
      : null

    debouncedSaveSettings(filterValues, accountLogin, repoFullName)
  }, [filters, selectedAccount, selectedRepo])
}
