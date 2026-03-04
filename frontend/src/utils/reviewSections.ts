import type { ReviewJSON, ReviewRecommendation, ReviewSectionJSON } from '../api/types'

export interface ReviewSection {
  key: string
  heading: string
  content: string
}

const SECTION_HEADINGS = [
  'Critical Issues',
  'Major Concerns',
  'Minor Issues',
  'Recommendations',
]

// All known review headings that act as section terminators
const ALL_KNOWN_HEADINGS = [
  ...SECTION_HEADINGS,
  'Positive Highlights',
  'Summary',
  'Score',
]

// Build a terminator lookahead that only matches known section headings,
// not arbitrary bold text like **High Priority:** inside a section
const HEADING_TERMINATORS = ALL_KNOWN_HEADINGS
  .map(h => `\\n\\*\\*${h.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\*\\*`)
  .join('|')

/**
 * Extract full-text sections from review markdown content.
 * Looks for bold section headings like **Critical Issues** and captures
 * everything until the next known section heading, horizontal rule, or ## heading.
 */
export function parseReviewSections(content: string): ReviewSection[] {
  const sections: ReviewSection[] = []
  if (!content) return sections

  for (const heading of SECTION_HEADINGS) {
    const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const pattern = new RegExp(
      `\\*\\*${escaped}\\*\\*\\s*([\\s\\S]*?)(?=\\n---(?:\\s|$)|\\n##\\s|${HEADING_TERMINATORS}|$)`,
      'i'
    )
    const match = content.match(pattern)
    if (match && match[1].trim()) {
      sections.push({
        key: heading.toLowerCase().replace(/\s+/g, '-'),
        heading,
        content: match[1].trim(),
      })
    }
  }

  return sections
}

/**
 * Convert a structured JSON section into markdown text for display.
 */
function formatSectionToMarkdown(section: ReviewSectionJSON): string {
  if (!section.issues.length) return 'None'

  return section.issues.map((issue, idx) => {
    const parts: string[] = [`**${idx + 1}. ${issue.title}**`]
    const loc = issue.location
    let locStr = loc.file
    if (loc.start_line != null && loc.end_line != null && loc.start_line !== loc.end_line) {
      locStr += `:${loc.start_line}-${loc.end_line}`
    } else if (loc.start_line != null) {
      locStr += `:${loc.start_line}`
    }
    if (locStr) parts.push(`- Location: \`${locStr}\``)
    if (issue.problem) parts.push(`- Problem: ${issue.problem}`)
    if (issue.fix) parts.push(`- Fix: ${issue.fix}`)
    if (issue.code_snippet) parts.push(`\n\`\`\`\n${issue.code_snippet}\n\`\`\``)
    return parts.join('\n')
  }).join('\n\n')
}

/**
 * Convert structured recommendations into markdown text for display.
 */
function formatRecommendationsToMarkdown(recs: ReviewRecommendation[]): string {
  const priorityLabels: Record<string, string> = {
    must_fix: 'Must Fix Before Merge:',
    high: 'High Priority:',
    medium: 'Medium Priority:',
    low: 'Low Priority:',
  }

  const lines: string[] = []
  let currentPriority: string | null = null
  let num = 1

  for (const rec of recs) {
    const p = rec.priority || 'medium'
    if (p !== currentPriority) {
      if (currentPriority !== null) lines.push('')
      lines.push(`**${priorityLabels[p] || `${p}:`}**`)
      currentPriority = p
    }
    lines.push(`${num}. ${rec.text}`)
    num++
  }

  return lines.join('\n')
}

/**
 * Extract sections from structured JSON review data (preferred path).
 */
export function sectionsFromJSON(reviewJson: ReviewJSON): ReviewSection[] {
  const sections = reviewJson.sections
    .filter(section => section.issues.length > 0)
    .map(section => ({
      key: section.type === 'critical' ? 'critical-issues'
        : section.type === 'major' ? 'major-concerns'
        : 'minor-issues',
      heading: section.display_name,
      content: formatSectionToMarkdown(section),
    }))

  if (reviewJson.recommendations?.length) {
    sections.push({
      key: 'recommendations',
      heading: 'Recommendations',
      content: formatRecommendationsToMarkdown(reviewJson.recommendations),
    })
  }

  return sections
}

/**
 * Get review sections, using JSON data when available with markdown fallback.
 */
export function getReviewSections(content?: string, contentJson?: ReviewJSON | null): ReviewSection[] {
  if (contentJson) return sectionsFromJSON(contentJson)
  return parseReviewSections(content || '')
}
