import { useEffect, useRef } from 'react'

/**
 * Polls a callback function at a specified interval
 * Automatically cleans up on unmount or when enabled changes
 */
export function usePolling(
  callback: () => void | Promise<void>,
  interval: number,
  enabled: boolean = true
) {
  const savedCallback = useRef(callback)

  // Update callback ref when it changes
  useEffect(() => {
    savedCallback.current = callback
  }, [callback])

  // Set up polling interval
  useEffect(() => {
    if (!enabled) {
      return
    }

    const tick = async () => {
      await savedCallback.current()
    }

    const id = setInterval(tick, interval)
    return () => clearInterval(id)
  }, [interval, enabled])
}
