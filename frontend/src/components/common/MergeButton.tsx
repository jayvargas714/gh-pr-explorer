import { useEffect, useState } from 'react'
import { fetchMergeInfo, mergePR } from '../../api/prs'
import {
  MERGE_METHODS, MergeInfo, MergeMessage, MergeMethod, canMerge, defaultMergeMethod, messageOverrides,
} from '../../utils/prActions'
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

type MessageMethod = Exclude<MergeMethod, 'rebase'>
const EMPTY_MESSAGE: MergeMessage = { subject: '', body: '' }

function MergeModal({
  repo, prNumber, title, ciStatus, behindBy, headSha, onDone, onClose,
}: MergeButtonProps & { onClose: () => void }) {
  const [info, setInfo] = useState<MergeInfo | null>(null)
  const [infoState, setInfoState] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [method, setMethod] = useState<MergeMethod>('squash')
  // One editable message per method, so switching methods never loses an edit.
  const [drafts, setDrafts] = useState<Record<MessageMethod, MergeMessage>>({
    squash: EMPTY_MESSAGE, merge: EMPTY_MESSAGE,
  })
  const [deleteBranch, setDeleteBranch] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const [owner, name] = repo.split('/')
    fetchMergeInfo(owner, name, prNumber)
      .then((resp) => {
        if (cancelled) return
        setInfo(resp)
        setDrafts({
          squash: { subject: resp.methods.squash.subject, body: resp.methods.squash.body },
          merge: { subject: resp.methods.merge.subject, body: resp.methods.merge.body },
        })
        setMethod(defaultMergeMethod(resp))
        setInfoState('ready')
      })
      .catch(() => {
        if (!cancelled) setInfoState('failed')
      })
    return () => {
      cancelled = true
    }
  }, [repo, prNumber])

  const messageMethod: MessageMethod | null = method === 'rebase' ? null : method
  const draft = messageMethod ? drafts[messageMethod] : null
  const defaults: MergeMessage | null =
    info && messageMethod
      ? { subject: info.methods[messageMethod].subject, body: info.methods[messageMethod].body }
      : null
  const edited = !!draft && !!defaults && (draft.subject !== defaults.subject || draft.body !== defaults.body)
  const subjectMissing = !!draft && infoState === 'ready' && draft.subject.trim() === ''

  const updateDraft = (patch: Partial<MergeMessage>) => {
    if (!messageMethod) return
    setDrafts((d) => ({ ...d, [messageMethod]: { ...d[messageMethod], ...patch } }))
  }

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
      await mergePR(owner, name, prNumber, {
        method,
        deleteBranch,
        headSha,
        ...messageOverrides(method, draft ?? EMPTY_MESSAGE, defaults),
      })
      onClose()
      onDone?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Merge failed')
      setBusy(false)
    }
  }

  return (
    <Modal onClose={busy ? () => {} : onClose} title={`Merge ${repo}#${prNumber}`} size="md">
      <div className="mx-merge-modal">
        {title && <p className="mx-merge-modal__title">{title}</p>}
        {warnings.length > 0 && (
          <Alert variant="warning">
            {warnings.join(' ')} GitHub will refuse the merge if branch protection requires otherwise.
          </Alert>
        )}
        {infoState === 'failed' && (
          <Alert variant="info">
            Couldn't load GitHub's default merge message. Leave the fields empty to use it, or write your own.
          </Alert>
        )}
        {error && <Alert variant="error">{error}</Alert>}

        <fieldset className="mx-merge-modal__methods" disabled={busy}>
          <legend className="mx-merge-modal__label">Merge method</legend>
          {MERGE_METHODS.map((m) => {
            const disallowed = !!info && !info.methods[m.value].allowed
            return (
              <label
                key={m.value}
                className={`mx-merge-modal__method${disallowed ? ' mx-merge-modal__method--disabled' : ''}`}
                data-tooltip={disallowed ? 'Disabled in repo settings' : undefined}
              >
                <input
                  type="radio"
                  name={`merge-method-${repo}-${prNumber}`}
                  value={m.value}
                  checked={method === m.value}
                  disabled={disallowed}
                  onChange={() => setMethod(m.value)}
                />
                <span className="mx-merge-modal__method-label">{m.label}</span>
                <span className="mx-merge-modal__method-hint">{m.hint}</span>
              </label>
            )
          })}
        </fieldset>

        {infoState === 'loading' ? (
          <p className="mx-merge-modal__hint">Loading GitHub's merge message…</p>
        ) : draft ? (
          <div className="mx-merge-modal__message">
            <div className="mx-merge-modal__message-header">
              <span className="mx-merge-modal__label">Commit message</span>
              {edited && (
                <button
                  type="button"
                  className="mx-merge-modal__reset"
                  onClick={() => defaults && updateDraft(defaults)}
                  disabled={busy}
                >
                  Reset to GitHub default
                </button>
              )}
            </div>
            <input
              type="text"
              className="mx-merge-modal__subject"
              value={draft.subject}
              placeholder={infoState === 'failed' ? "GitHub's default subject" : 'Subject'}
              onChange={(e) => updateDraft({ subject: e.target.value })}
              disabled={busy}
              aria-label="Commit subject"
            />
            <textarea
              className="mx-merge-modal__body"
              value={draft.body}
              rows={8}
              placeholder={infoState === 'failed' ? "GitHub's default description" : 'Description (optional)'}
              onChange={(e) => updateDraft({ body: e.target.value })}
              disabled={busy}
              aria-label="Commit description"
            />
            {subjectMissing && <p className="mx-merge-modal__field-error">A commit subject is required.</p>}
          </div>
        ) : (
          <p className="mx-merge-modal__hint">Rebase keeps each commit's message.</p>
        )}

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
          <Button
            variant="primary"
            size="sm"
            onClick={submit}
            disabled={busy || infoState === 'loading' || subjectMissing}
          >
            {busy ? 'Merging…' : 'Confirm merge'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
