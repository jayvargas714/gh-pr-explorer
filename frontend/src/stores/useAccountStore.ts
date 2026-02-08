import { create } from 'zustand'
import { Account, Repository } from '../api/types'

interface AccountState {
  // Accounts
  accounts: Account[]
  selectedAccount: Account | null
  accountsLoading: boolean
  accountsError: string | null

  // Repositories
  repos: Repository[]
  selectedRepo: Repository | null
  repoSearch: string
  reposLoading: boolean
  reposError: string | null

  // Actions
  setAccounts: (accounts: Account[]) => void
  setSelectedAccount: (account: Account | null) => void
  setAccountsLoading: (loading: boolean) => void
  setAccountsError: (error: string | null) => void

  setRepos: (repos: Repository[]) => void
  setSelectedRepo: (repo: Repository | null) => void
  setRepoSearch: (search: string) => void
  setReposLoading: (loading: boolean) => void
  setReposError: (error: string | null) => void

  // Computed
  filteredRepos: () => Repository[]
}

export const useAccountStore = create<AccountState>((set, get) => ({
  // Accounts
  accounts: [],
  selectedAccount: null,
  accountsLoading: false,
  accountsError: null,

  // Repositories
  repos: [],
  selectedRepo: null,
  repoSearch: '',
  reposLoading: false,
  reposError: null,

  // Actions
  setAccounts: (accounts) => set({ accounts }),
  setSelectedAccount: (account) => set({ selectedAccount: account }),
  setAccountsLoading: (loading) => set({ accountsLoading: loading }),
  setAccountsError: (error) => set({ accountsError: error }),

  setRepos: (repos) => set({ repos }),
  setSelectedRepo: (repo) => set({ selectedRepo: repo }),
  setRepoSearch: (search) => set({ repoSearch: search }),
  setReposLoading: (loading) => set({ reposLoading: loading }),
  setReposError: (error) => set({ reposError: error }),

  // Computed
  filteredRepos: () => {
    const { repos, repoSearch } = get()
    if (!repoSearch) return repos
    const search = repoSearch.toLowerCase()
    return repos.filter(
      (repo) =>
        repo.name.toLowerCase().includes(search) ||
        repo.description?.toLowerCase().includes(search)
    )
  },
}))
