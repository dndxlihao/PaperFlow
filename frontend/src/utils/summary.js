const HEADING_RE = /^\s{0,3}#{1,6}\s+(.+)$/

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInline(text) {
  let safe = escapeHtml(text)
  safe = safe.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
  safe = safe.replace(/__(.+?)__/g, '<b>$1</b>')
  safe = safe.replace(/`([^`]+)`/g, '$1')
  return safe
}

export function normalizeSummaryHtml(raw) {
  if (!raw) return ''

  let text = String(raw).replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
  text = text.replace(/^```(?:html|markdown|md)?\s*/i, '').replace(/\s*```$/, '').trim()
  if (!text) return ''

  // Convert Markdown headings first so mixed content can still render well.
  text = text.replace(/^\s{0,3}#{1,6}\s+(.+)$/gm, (_, title) => `<h4>${title.trim()}</h4>`)

  const hasHtml = /<\/?(h[1-6]|p|b|strong|ul|ol|li|br)\b/i.test(text)
  if (hasHtml) {
    text = text
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
      .replace(/__(.+?)__/g, '<b>$1</b>')
      .replace(/<p>\s*([\s\S]*?)\s*<\/p>/gi, (_, inner) => {
        const clean = String(inner || '').trim()
        if (!clean) return '<p></p>'
        if (/^(　　|&emsp;&emsp;|&nbsp;&nbsp;)/.test(clean)) return `<p>${clean}</p>`
        return `<p>　　${clean}</p>`
      })
    return text
  }

  const lines = text.split('\n')
  const blocks = []
  let paragraph = []

  const flushParagraph = () => {
    if (paragraph.length === 0) return
    const merged = paragraph.join(' ').replace(/\s+/g, ' ').trim()
    if (merged) blocks.push(`<p>　　${renderInline(merged)}</p>`)
    paragraph = []
  }

  for (const line of lines) {
    const stripped = line.trim()
    if (!stripped) {
      flushParagraph()
      continue
    }

    const headingMatch = stripped.match(HEADING_RE)
    if (headingMatch) {
      flushParagraph()
      blocks.push(`<h4>${renderInline(headingMatch[1].trim())}</h4>`)
      continue
    }

    paragraph.push(stripped.replace(/^[-*•]\s+/, ''))
  }
  flushParagraph()

  if (blocks.length === 0) {
    const fallback = text.replace(/\s+/g, ' ').trim()
    return `<p>　　${renderInline(fallback)}</p>`
  }

  return blocks.join('\n')
}
