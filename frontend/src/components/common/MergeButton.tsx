import { useState } from 'react'
import { mergePR } from '../../api/prs'
import { MERGE_METHODS, MergeMethod, canMerge } from '../../utils/prActions'
import { Alert } from './Alert'
import { Button } from './Button'
import { Modal } from './Modal'

interface MergeButtonProps {
  /** `owner/name` */
  repo: string
  prNumber: number
  title: string | null
  prState: string | null | undefined
  isDraft: boolean
  reviewDecision: string | null | undefined
  ciStatus: string | null | undefined
  behindBy: number | null | undefined
  /** Head SHA the operator is looking at; the merge is refused if it moved. */
  headSha: string | null | undefined
  /** Called after GitHub merged the PR, so the host can refresh its data. */
  onDone?: () => void
}

/** "⇪ Merge" for open, non-draft, approved PRs; opens a confirm dialog with
 * the merge method and delete-branch choice. */
export function MergeButton(props: MergeButtonProps) {
  const [open, setOpen] = useState(false)
  if (!canMerge(props)) return null

  return (
    <span className="mx-pr-action" onClick={(e) => e.stopPropagation()}>
      <Button
        variant="ghost"
        size="sm"
        className="mx-merge-btn"
        onClick={() => setOpen(true)}
        data-tooltip="Merge this pull request"
      >
        ⇪ Merge
      </Button>
      {open && <MergeModal {...props} onClose={() => setOpen(false)} />}
    </span>
  )
}

function MergeModal({
  repo, prNumber, title, ciStatus, behindBy, headSha, onDone, onClose,
}: MergeButtonProps & { onClose: () => void }) {
  const [method, setMethod] = useState<MergeMethod>('squash')
  const [deleteBranch, setDeleteBranch] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const warnings: string[] = []
  if (ciStatus && ciStatus !== 'success') warnings.push(`CI is ${ciStatus}.`)
  if (behindBy && behindBy > 0) {
    warnings.push(`The branch is ${behindBy} commit${behindBy === 1 ? '' : 's'} behind its base.`)
  }

  const submit = async () => {
    if (busy) return
    const [owner, name] = repo.split('/')
    setBusy(true)
    setError(null)
    try {
      await mergePR(owner, name, prNumber, { method, deleteBranch, headSha })
      onClose()
      onDone?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Merge failed')
      setBusy(false)
    }
  }

  return (
    <Modal onClose={busy ? () => {} : onClose} title={`Merge ${repo}#${prNumber}`} size="sm">
      <div className="mx-merge-modal">
        {title && <p className="mx-merge-modal__title">{title}</p>}
        {warnings.length > 0 && (
          <Alert variant="warning">
            {warnings.join(' ')} GitHub will refuse the merge if branch protection requires otherwise.
          </Alert>
        )}
        {error && <Alert variant="error">{error}</Alert>}

        <fieldset className="mx-merge-modal__methods" disabled={busy}>
          <legend className="mx-merge-modal__label">Merge method</legend>
          {MERGE_METHODS.map((m) => (
            <label key={m.value} className="mx-merge-modal__method">
              <input
                type="radio"
                name={`merge-method-${repo}-${prNumber}`}
                value={m.value}
                checked={method === m.value}
                onChange={() => setMethod(m.value)}
              />
              <span className="mx-merge-modal__method-label">{m.label}</span>
              <span className="mx-merge-modal__method-hint">{m.hint}</span>
            </label>
          ))}
        </fieldset>

        <label className="mx-merge-modal__checkbox">
          <input
            type="checkbox"
            checked={deleteBranch}
            disabled={busy}
            onChange={(e) => setDeleteBranch(e.target.checked)}
          />
          Delete branch after merge
        </label>

        <div className="mx-merge-modal__actions">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={busy}>
            {busy ? 'Merging…' : 'Confirm merge'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
