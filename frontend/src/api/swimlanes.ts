import { api } from './client'
import {
  SwimlaneBoardResponse,
  SwimlaneColor,
  SwimlaneDeleteResponse,
  SwimlaneMoveResponse,
  SwimlaneResponse,
  SwimlanesListResponse,
} from './types'

export function fetchSwimlaneBoard(): Promise<SwimlaneBoardResponse> {
  return api.get<SwimlaneBoardResponse>('/swimlanes/board')
}

export function createSwimlane(name: string, color: SwimlaneColor): Promise<SwimlaneResponse> {
  return api.post<SwimlaneResponse>('/swimlanes', { name, color })
}

export function updateSwimlane(
  id: number,
  patch: { name?: string; color?: SwimlaneColor }
): Promise<SwimlaneResponse> {
  return api.put<SwimlaneResponse>(`/swimlanes/${id}`, patch)
}

// PATCH not provided by client wrapper; use a raw fetch to keep client.ts unchanged.
// Swap to api.put-style if PATCH is added later.
export async function patchSwimlane(
  id: number,
  patch: { name?: string; color?: SwimlaneColor }
): Promise<SwimlaneResponse> {
  const res = await fetch(`/api/swimlanes/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.error || `Request failed with status ${res.status}`)
  }
  return res.json()
}

export function deleteSwimlane(id: number): Promise<SwimlaneDeleteResponse> {
  return api.delete<SwimlaneDeleteResponse>(`/swimlanes/${id}`)
}

export function reorderSwimlanes(order: number[]): Promise<SwimlanesListResponse> {
  return api.put<SwimlanesListResponse>('/swimlanes/reorder', { order })
}

export function setDefaultSwimlane(id: number): Promise<SwimlaneResponse> {
  return api.put<SwimlaneResponse>(`/swimlanes/${id}/default`)
}

export function moveSwimlaneCard(
  queueItemId: number,
  toLaneId: number,
  toPosition: number
): Promise<SwimlaneMoveResponse> {
  return api.put<SwimlaneMoveResponse>('/swimlanes/cards/move', {
    queueItemId,
    toLaneId,
    toPosition,
  })
}
