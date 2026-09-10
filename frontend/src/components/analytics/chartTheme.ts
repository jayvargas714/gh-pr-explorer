import { CSSProperties, useMemo } from 'react'
import { useUIStore } from '../../stores/useUIStore'

interface ChartTheme {
  text: string
  grid: string
  tooltipStyle: CSSProperties
  primary: string
  success: string
  error: string
  info: string
}

const readToken = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/**
 * Resolves the current theme's CSS custom properties to concrete values.
 * Recharts sets SVG stroke/fill attributes directly, where var() does not
 * resolve, so these must be read from the computed style.
 */
export function useChartTheme(): ChartTheme {
  const darkMode = useUIStore((state) => state.darkMode)

  return useMemo(() => {
    const text = readToken('--mx-color-text-secondary')
    const grid = readToken('--mx-color-border')
    const surface = readToken('--mx-color-surface')
    const textPrimary = readToken('--mx-color-text-primary')
    const primary = readToken('--mx-color-primary')
    const success = readToken('--mx-color-success')
    const error = readToken('--mx-color-error')
    const info = readToken('--mx-color-info')

    return {
      text,
      grid,
      tooltipStyle: {
        backgroundColor: surface,
        border: `1px solid ${grid}`,
        borderRadius: 8,
        color: textPrimary,
      },
      primary,
      success,
      error,
      info,
    }
    // darkMode itself isn't read here, but it drives the `.matrix-light` class
    // that getComputedStyle reads through — keep it as the recompute trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [darkMode])
}
