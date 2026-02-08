import { useEffect, useState, useRef } from 'react'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchRepos } from '../../api/repos'
import { Input } from '../common/Input'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { useClickOutside } from '../../hooks/useClickOutside'

export function RepoSelector() {
  const {
    selectedAccount,
    repos,
    selectedRepo,
    repoSearch,
    reposLoading,
    reposError,
    setRepos,
    setSelectedRepo,
    setRepoSearch,
    setReposLoading,
    setReposError,
    filteredRepos,
  } = useAccountStore()

  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useClickOutside(dropdownRef, () => setIsOpen(false))

  // Load repos when account changes
  useEffect(() => {
    if (selectedAccount) {
      loadRepos()
    } else {
      setRepos([])
      setSelectedRepo(null)
    }
  }, [selectedAccount])

  const loadRepos = async () => {
    if (!selectedAccount) return

    try {
      setReposLoading(true)
      setReposError(null)
      const response = await fetchRepos(selectedAccount.login)
      setRepos(response.repos)
    } catch (error) {
      setReposError(error instanceof Error ? error.message : 'Failed to load repositories')
    } finally {
      setReposLoading(false)
    }
  }

  const handleRepoSelect = (repo: any) => {
    setSelectedRepo(repo)
    setIsOpen(false)
    setRepoSearch('')
  }

  if (!selectedAccount) return null

  if (reposError) {
    return (
      <div className="mx-repo-selector">
        <Alert variant="error" onClose={() => setReposError(null)}>
          {reposError}
        </Alert>
      </div>
    )
  }

  return (
    <div className="mx-repo-selector" ref={dropdownRef}>
      <label className="mx-repo-selector__label">Repository</label>

      <div className="mx-repo-selector__dropdown">
        <button
          className="mx-repo-selector__trigger"
          onClick={() => setIsOpen(!isOpen)}
          disabled={reposLoading}
        >
          {reposLoading ? (
            <>
              <Spinner size="sm" />
              <span>Loading repositories...</span>
            </>
          ) : selectedRepo ? (
            <>
              <span className="mx-repo-selector__name">{selectedRepo.name}</span>
              {selectedRepo.isPrivate && (
                <span className="mx-repo-badge">Private</span>
              )}
            </>
          ) : (
            <span className="mx-repo-selector__placeholder">Select a repository</span>
          )}
          <span className="mx-repo-selector__arrow">▼</span>
        </button>

        {isOpen && !reposLoading && (
          <div className="mx-repo-selector__menu">
            <div className="mx-repo-selector__search">
              <Input
                type="text"
                placeholder="Search repositories..."
                value={repoSearch}
                onChange={(e) => setRepoSearch(e.target.value)}
                autoFocus
              />
            </div>

            <div className="mx-repo-selector__list">
              {filteredRepos().length === 0 ? (
                <div className="mx-repo-selector__empty">No repositories found</div>
              ) : (
                filteredRepos().map((repo) => (
                  <button
                    key={`${repo.owner.login}/${repo.name}`}
                    className={`mx-repo-selector__item ${
                      selectedRepo?.name === repo.name ? 'mx-repo-selector__item--active' : ''
                    }`}
                    onClick={() => handleRepoSelect(repo)}
                  >
                    <div className="mx-repo-selector__item-main">
                      <span className="mx-repo-selector__item-name">{repo.name}</span>
                      {repo.isPrivate && (
                        <span className="mx-repo-badge mx-repo-badge--small">Private</span>
                      )}
                    </div>
                    {repo.description && (
                      <span className="mx-repo-selector__item-desc">{repo.description}</span>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
