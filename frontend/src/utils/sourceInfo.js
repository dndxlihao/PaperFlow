export default function getSourceInfo(paper) {
  const arn = paper.articleNumber || ''
  const isUserUpload = arn.startsWith('ugc_')
  const publicationTitle = (paper.publicationTitle || '').trim()
  const pub = publicationTitle.toLowerCase()

  const buildIeeeTransactionAbbr = (name) => {
    const prefix = 'ieee transactions on '
    if (!name.startsWith(prefix)) return ''
    const stopWords = new Set(['and', 'of', 'the', 'for', 'in', 'on', 'to', 'with', '&'])
    const normalized = name
      .slice(prefix.length)
      .replace(/[()/:,-]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    if (!normalized) return ''
    const letters = normalized
      .split(' ')
      .filter(Boolean)
      .filter(word => !stopWords.has(word))
      .map(word => word[0]?.toUpperCase() || '')
      .join('')
    if (letters.length < 2) return ''
    return `T${letters}`
  }

  const buildGenericJournalAbbr = (name) => {
    const stopWords = new Set(['and', 'of', 'the', 'for', 'in', 'on', 'to', 'with', '&', 'journal'])
    const normalized = String(name || '')
      .replace(/[()/:,.-]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    if (!normalized) return ''

    // Already an abbreviation-like token, e.g. TSG / TPWRS / AE.
    const compact = normalized.replace(/\s+/g, '')
    if (/^[A-Za-z][A-Za-z0-9-]{1,10}$/.test(compact) && compact.length <= 8) {
      return compact.toUpperCase()
    }

    const letters = normalized
      .split(' ')
      .filter(Boolean)
      .filter(word => !stopWords.has(word.toLowerCase()))
      .map(word => word[0]?.toUpperCase() || '')
      .join('')

    if (letters.length >= 2 && letters.length <= 8) return letters
    if (letters.length > 8) return letters.slice(0, 8)
    return ''
  }

  const ieeeJournalAliases = [
    { keywords: ['industrial informatics'], label: 'TII' },
    { keywords: ['smart grid'], label: 'TSG', cls: 'badge-tsg' },
    { keywords: ['sustainable energy'], label: 'TSTE', cls: 'badge-tste' },
    { keywords: ['industrial electronics'], label: 'TIE', cls: 'badge-tie' },
    { keywords: ['power systems'], label: 'TPWRS', cls: 'badge-tpwrs' },
    { keywords: ['power delivery'], label: 'TPWRD' },
    { keywords: ['power electronics'], label: 'TPEL' },
    { keywords: ['energy conversion'], label: 'TEC' },
    { keywords: ['neural networks and learning systems'], label: 'TNNLS' },
    { keywords: ['pattern analysis and machine intelligence'], label: 'TPAMI' },
    { keywords: ['wireless communications'], label: 'TWC' },
    { keywords: ['communications'], label: 'TCOM' },
    { keywords: ['network science and engineering'], label: 'TNSE' },
    { keywords: ['information forensics and security'], label: 'TIFS' },
    { keywords: ['cybernetics'], label: 'TCYB' },
    { keywords: ['internet of things journal'], label: 'IoT-J' },
    { keywords: ['transactions on automation science and engineering'], label: 'TASE' },
    { keywords: ['systems, man, and cybernetics'], label: 'TSMC' },
    { keywords: ['control systems technology'], label: 'TCST' },
    { keywords: ['control systems letters'], label: 'L-CSS' },
    { keywords: ['control of network systems'], label: 'TCNS' },
    { keywords: ['signal processing letters'], label: 'SPL' },
    { keywords: ['signal processing magazine'], label: 'SPM' },
    { keywords: ['ieee access'], label: 'IEEE Access' },
  ]

  // Conferences
  if (pub.includes('iclr')) return { label: 'ICLR', cls: 'badge-iclr' }
  if (pub.includes('cvpr')) return { label: 'CVPR', cls: 'badge-cvpr' }
  if (pub.includes('acl') && !pub.includes('acle')) return { label: 'ACL', cls: 'badge-acl' }
  if (pub.includes('aaai')) return { label: 'AAAI', cls: 'badge-aaai' }
  if (pub.includes('icml')) return { label: 'ICML', cls: 'badge-icml' }
  if (pub.includes('kdd')) return { label: 'KDD', cls: 'badge-kdd' }
  if (pub.includes('ijcai')) return { label: 'IJCAI', cls: 'badge-ijcai' }
  if (pub.includes('neurips')) return { label: 'NeurIPS', cls: 'badge-neurips' }

  // arXiv
  if (arn.startsWith('arxiv_')) return { label: 'arXiv', cls: 'badge-arxiv' }

  // IEEE Journals – abbreviations
  const ieeeMatch = ieeeJournalAliases.find(entry => entry.keywords.every(k => pub.includes(k)))
  if (ieeeMatch) return { label: ieeeMatch.label, cls: ieeeMatch.cls || 'badge-ieee' }
  if (pub.startsWith('ieee transactions on ')) {
    const autoAbbr = buildIeeeTransactionAbbr(pub)
    if (autoAbbr) return { label: autoAbbr, cls: 'badge-ieee' }
  }

  // Energy journals – abbreviations
  if (pub.includes('applied energy')) return { label: 'AE', cls: 'badge-ae' }
  if (pub.includes('renewable') && pub.includes('sustainable')) return { label: 'RSER', cls: 'badge-rser' }
  if (pub.includes('energy')) return { label: 'Energy', cls: 'badge-energy' }

  // User-upload cards: when publicationTitle exists, use abbreviation; otherwise show Creator.
  if (isUserUpload) {
    if (!publicationTitle) return { label: 'Creator', cls: 'badge-user-upload' }
    const autoAbbr = buildIeeeTransactionAbbr(pub) || buildGenericJournalAbbr(publicationTitle)
    if (autoAbbr) return { label: autoAbbr, cls: 'badge-user-upload' }
    return { label: publicationTitle, cls: 'badge-user-upload' }
  }

  // Fallback
  if (arn.startsWith('elsevier_')) return { label: paper.publicationTitle || 'Elsevier', cls: 'badge-elsevier' }
  if (arn.startsWith('crossref_')) return { label: paper.publicationTitle || 'CrossRef', cls: 'badge-crossref' }
  return { label: paper.publicationTitle || 'IEEE', cls: 'badge-ieee' }
}
