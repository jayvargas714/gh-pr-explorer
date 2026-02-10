import { useState, useEffect } from 'react'
import { fetchQueueNotes, addQueueNote, deleteQueueNote } from '../../api/queue'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { Alert } from '../common/Alert'
import { Spinner } from '../common/Spinner'
import { formatRelativeTime } from '../../utils/formatters'
import type { QueueNote } from '../../api/types'

interface NotesModalProps {
  prNumber: number
  repo: string
  onClose: () => void
  onUpdate: () => void
}

export function NotesModal({ prNumber, repo, onClose, onUpdate }: NotesModalProps) {
  const [notes, setNotes] = useState<QueueNote[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newNoteContent, setNewNoteContent] = useState('')
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    loadNotes()
  }, [])

  const loadNotes = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await fetchQueueNotes(prNumber, repo)
      setNotes(response.notes)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load notes')
    } finally {
      setLoading(false)
    }
  }

  const handleAddNote = async () => {
    if (!newNoteContent.trim() || adding) return

    try {
      setAdding(true)
      await addQueueNote(prNumber, repo, newNoteContent)
      setNewNoteContent('')
      await loadNotes()
      onUpdate() // Refresh queue to update note count
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add note')
    } finally {
      setAdding(false)
    }
  }

  const handleDeleteNote = async (noteId: number) => {
    try {
      await deleteQueueNote(noteId)
      await loadNotes()
      onUpdate() // Refresh queue to update note count
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete note')
    }
  }

  return (
    <Modal title={`Notes for PR #${prNumber}`} onClose={onClose} size="md">
      {loading ? (
        <div className="mx-notes-modal__loading">
          <Spinner size="md" />
          <p>Loading notes...</p>
        </div>
      ) : error ? (
        <Alert variant="error">{error}</Alert>
      ) : (
        <>
          <div className="mx-notes-modal__list">
            {notes.length === 0 ? (
              <p className="mx-notes-modal__empty">No notes yet. Add one below!</p>
            ) : (
              notes.map((note) => (
                <div key={note.id} className="mx-notes-modal__item">
                  <div className="mx-notes-modal__item-content">{note.content}</div>
                  <div className="mx-notes-modal__item-footer">
                    <span className="mx-notes-modal__item-time">
                      {formatRelativeTime(note.createdAt)}
                    </span>
                    <Button variant="ghost" size="sm" onClick={() => handleDeleteNote(note.id)}>
                      Delete
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="mx-notes-modal__add">
            <textarea
              className="mx-notes-modal__textarea"
              placeholder="Add a note..."
              value={newNoteContent}
              onChange={(e) => setNewNoteContent(e.target.value)}
              rows={3}
            />
            <Button variant="primary" onClick={handleAddNote} disabled={adding || !newNoteContent.trim()}>
              {adding ? 'Adding...' : 'Add Note'}
            </Button>
          </div>
        </>
      )}
    </Modal>
  )
}
