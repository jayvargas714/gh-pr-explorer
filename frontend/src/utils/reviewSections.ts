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

/**
 * Extract full-text sections from review markdown content.
 * Looks for bold section headings like **Critical Issues** and captures
 * everything until the next section heading or horizontal rule.
 */
export function parseReviewSections(content: string): ReviewSection[] {
  const sections: ReviewSection[] = []
  if (!content) return sections

  for (const heading of SECTION_HEADINGS) {
    const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const pattern = new RegExp(
      `\\*\\*${escaped}\\*\\*\\s*([\\s\\S]*?)(?=\\n---(?:\\s|$)|\\n\\*\\*[A-Z]|$)`,
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
