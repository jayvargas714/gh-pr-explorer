import { api } from './client'
import { MergeQueueResponse, QueueNotesResponse, MessageResponse } from './types'

/**
 * Fetch merge queue
 */
export async function fetchMergeQueue(): Promise<MergeQueueResponse> {
  return api.get<MergeQueueResponse>('/merge-queue')
}

/**
 * Add PR to merge queue
 */
export async function addToQueue(data: {
  number: number
  title: string
  url: string
  author: string
  repo: string
  additions?: number
  deletions?: number
}): Promise<MessageResponse> {
  return api.post<MessageResponse>('/merge-queue', data)
}

/**
 * Remove PR from merge queue
 */
export async function removeFromQueue(
  prNumber: number,
  repo: string
): Promise<MessageResponse> {
  return api.delete<MessageResponse>(`/merge-queue/${prNumber}?repo=${repo}`)
}

/**
 * Reorder merge queue
 */
export async function reorderQueue(fromIndex: number, toIndex: number) {
  return api.put('/merge-queue/reorder', { from_index: fromIndex, to_index: toIndex })
}

/**
 * Get notes for a queue item
 */
export async function getQueueNotes(
  prNumber: number,
  repo: string
): Promise<QueueNotesResponse> {
  return api.get<QueueNotesResponse>(`/merge-queue/${prNumber}/notes?repo=${repo}`)
}

// Alias for consistency
export const fetchQueueNotes = getQueueNotes

/**
 * Add note to queue item
 */
export async function addQueueNote(
  prNumber: number,
  repo: string,
  content: string
): Promise<MessageResponse> {
  return api.post<MessageResponse>(`/merge-queue/${prNumber}/notes?repo=${repo}`, {
    content,
  })
}

/**
 * Delete queue note
 */
export async function deleteQueueNote(noteId: number): Promise<MessageResponse> {
  return api.delete<MessageResponse>(`/merge-queue/notes/${noteId}`)
}
