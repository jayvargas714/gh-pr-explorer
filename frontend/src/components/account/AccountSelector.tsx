import { useEffect } from 'react'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchAccounts } from '../../api/repos'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

export function AccountSelector() {
  const {
    accounts,
    selectedAccount,
    accountsLoading,
    accountsError,
    setAccounts,
    setSelectedAccount,
    setAccountsLoading,
    setAccountsError,
  } = useAccountStore()

  useEffect(() => {
    loadAccounts()
  }, [])

  const loadAccounts = async () => {
    try {
      setAccountsLoading(true)
      setAccountsError(null)
      const response = await fetchAccounts()
      setAccounts(response.accounts)
    } catch (error) {
      setAccountsError(error instanceof Error ? error.message : 'Failed to load accounts')
    } finally {
      setAccountsLoading(false)
    }
  }

  if (accountsLoading) {
    return (
      <div className="mx-account-selector mx-account-selector--loading">
        <Spinner size="sm" />
        <span>Loading accounts...</span>
      </div>
    )
  }

  if (accountsError) {
    return (
      <div className="mx-account-selector">
        <Alert variant="error" onClose={() => setAccountsError(null)}>
          {accountsError}
        </Alert>
      </div>
    )
  }

  return (
    <div className="mx-account-selector">
      <label className="mx-account-selector__label">Account / Organization</label>
      <div className="mx-account-selector__buttons">
        {accounts.map((account) => (
          <button
            key={account.login}
            className={`mx-account-button ${
              selectedAccount?.login === account.login ? 'mx-account-button--active' : ''
            }`}
            onClick={() => setSelectedAccount(account)}
          >
            <img
              src={account.avatar_url}
              alt={account.name}
              className="mx-account-button__avatar"
            />
            <div className="mx-account-button__info">
              <span className="mx-account-button__name">{account.login}</span>
              {account.is_personal && (
                <span className="mx-account-button__badge">Personal</span>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
