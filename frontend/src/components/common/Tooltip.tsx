import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

interface TooltipState {
  text: string
  x: number
  y: number
}

/**
 * Global tooltip provider that renders tooltips for any element with a
 * data-tooltip attribute. Uses a portal to escape overflow containers.
 * Mount once at the app root.
 */
export function TooltipProvider() {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const timeoutRef = useRef<number | null>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleMouseEnter = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest('[data-tooltip]') as HTMLElement | null
      if (!target) return
      const text = target.getAttribute('data-tooltip')
      if (!text) return

      // Clear any pending hide
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }

      const rect = target.getBoundingClientRect()
      setTooltip({
        text,
        x: rect.left + rect.width / 2,
        y: rect.top,
      })
    }

    const handleMouseLeave = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest('[data-tooltip]')
      if (!target) return
      timeoutRef.current = window.setTimeout(() => setTooltip(null), 50)
    }

    document.addEventListener('mouseover', handleMouseEnter)
    document.addEventListener('mouseout', handleMouseLeave)

    return () => {
      document.removeEventListener('mouseover', handleMouseEnter)
      document.removeEventListener('mouseout', handleMouseLeave)
      if (timeoutRef.current) clearTimeout(timeoutRef.current)
    }
  }, [])

  if (!tooltip) return null

  // Adjust position so tooltip doesn't overflow viewport
  const style: React.CSSProperties = {
    position: 'fixed',
    left: tooltip.x,
    top: tooltip.y,
    transform: 'translate(-50%, -100%)',
    marginTop: -6,
    zIndex: 9999,
  }

  return createPortal(
    <div ref={tooltipRef} className="mx-tooltip-portal" style={style}>
      {tooltip.text}
    </div>,
    document.body
  )
}
