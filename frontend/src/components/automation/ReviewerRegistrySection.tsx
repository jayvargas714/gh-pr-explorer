import { useState } from 'react'
import { Button } from '../common/Button'
import { useAutomationStore } from '../../stores/useAutomationStore'
import { ReviewerInfo } from '../../api/types'

const EMPTY_FORM = { key: '', label: '', agentName: '', promptContext: '' }

/** CRUD table for the reviewer registry. Builtins are locked: label and
 * prompt context stay editable, agent name and existence do not. */
export function ReviewerRegistrySection() {
  const reviewers = useAutomationStore((s) => s.reviewers)
  const saving = useAutomationStore((s) => s.saving)
  const addReviewer = useAutomationStore((s) => s.addReviewer)
  const editReviewer = useAutomationStore((s) => s.editReviewer)
  const removeReviewer = useAutomationStore((s) => s.removeReviewer)

  const [form, setForm] = useState(EMPTY_FORM)
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const startEdit = (reviewer: ReviewerInfo) => {
    setAdding(false)
    setEditingKey(reviewer.key)
    setForm({
      key: reviewer.key,
      label: reviewer.label,
      agentName: reviewer.agentName,
      promptContext: reviewer.promptContext ?? '',
    })
  }

  const cancel = () => {
    setEditingKey(null)
    setAdding(false)
    setForm(EMPTY_FORM)
  }

  const submit = async () => {
    const promptContext = form.promptContext.trim() ? form.promptContext : null
    const ok = editingKey
      ? await editReviewer(editingKey, {
          label: form.label,
          agentName: form.agentName,
          promptContext,
        })
      : await addReviewer({
          key: form.key.trim(),
          label: form.label,
          agentName: form.agentName,
          promptContext,
        })
    if (ok) cancel()
  }

  const editingBuiltin = editingKey !== null &&
    (reviewers.find((r) => r.key === editingKey)?.isBuiltin ?? false)

  return (
    <section className="mx-automation__section">
      <h3 className="mx-automation__section-title">Reviewer Registry</h3>
      <p className="mx-automation__intro">
        The reviewers that routing rules, pickers, and armed cards can use. Each maps a key
        to a Claude agent, with optional prompt context prepended to the review prompt.
        Builtins cannot be deleted or repointed to a different agent.
      </p>

      <table className="mx-automation__table">
        <thead>
          <tr>
            <th>Key</th>
            <th>Label</th>
            <th>Agent</th>
            <th>Context</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {reviewers.map((reviewer) => (
            <tr key={reviewer.key}>
              <td className="mx-automation__mono">
                {reviewer.key}
                {reviewer.isBuiltin && <span className="mx-automation__builtin-tag">builtin</span>}
              </td>
              <td>{reviewer.label}</td>
              <td className="mx-automation__mono">{reviewer.agentName}</td>
              <td className="mx-automation__context" title={reviewer.promptContext ?? ''}>
                {reviewer.promptContext ? `${reviewer.promptContext.slice(0, 60)}…` : '—'}
              </td>
              <td className="mx-automation__row-actions">
                <Button variant="ghost" size="sm" onClick={() => startEdit(reviewer)} disabled={saving}>
                  Edit
                </Button>
                {!reviewer.isBuiltin && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      if (window.confirm(`Delete reviewer '${reviewer.key}'?`)) {
                        removeReviewer(reviewer.key)
                      }
                    }}
                    disabled={saving}
                  >
                    Delete
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {(adding || editingKey) ? (
        <div className="mx-automation__reviewer-form">
          <div className="mx-automation__form-row">
            <input
              type="text"
              className="mx-input"
              placeholder="key (a-z, 0-9, -, _)"
              value={form.key}
              onChange={(e) => setForm({ ...form, key: e.target.value })}
              disabled={saving || editingKey !== null}
            />
            <input
              type="text"
              className="mx-input"
              placeholder="Label"
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              disabled={saving}
            />
            <input
              type="text"
              className="mx-input"
              placeholder="claude-agent-name"
              value={form.agentName}
              onChange={(e) => setForm({ ...form, agentName: e.target.value })}
              disabled={saving || editingBuiltin}
            />
          </div>
          <textarea
            className="mx-input mx-automation__context-input"
            placeholder="Optional prompt context prepended to the review prompt"
            value={form.promptContext}
            onChange={(e) => setForm({ ...form, promptContext: e.target.value })}
            disabled={saving}
            rows={3}
          />
          <div className="mx-automation__form-actions">
            <Button variant="ghost" size="sm" onClick={cancel} disabled={saving}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={submit} disabled={saving}>
              {editingKey ? 'Save reviewer' : 'Add reviewer'}
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="ghost" size="sm" onClick={() => { setAdding(true); setForm(EMPTY_FORM) }} disabled={saving}>
          + Add Reviewer
        </Button>
      )}
    </section>
  )
}
