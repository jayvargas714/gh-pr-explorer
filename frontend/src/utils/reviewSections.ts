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
