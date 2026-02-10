import { api } from './client'
import { MessageResponse } from './types'

/**
 * Get all settings
 */
export async function getAllSettings(): Promise<{ settings: Record<string, any> }> {
  return api.get('/settings')
}

/**
 * Get a specific setting
 */
export async function getSetting(key: string): Promise<{ key: string; value: any }> {
  return api.get(`/settings/${key}`)
}

/**
 * Set a setting value
 */
export async function setSetting(
  key: string,
  value: any
): Promise<{ key: string; value: any; message: string }> {
  return api.post(`/settings/${key}`, { value })
}

/**
 * Delete a setting
 */
export async function deleteSetting(key: string): Promise<MessageResponse> {
  return api.delete<MessageResponse>(`/settings/${key}`)
}
