import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import ForceGraph2D from 'react-force-graph-2d'
import api from '../api'
import StarRating from '../components/StarRating'
import './ScholarGraph.css'

/* ── palette ────────────────────────────────────────────────────── */
const PALETTE = [
  '#1B4332','#2D6A4F','#40916C','#52B788','#74C69D',
  '#95D5B2','#3A86A6','#457B9D','#6D597A','#B56576',
  '#E56B6F','#CDB4DB','#8E7DBE','#48BFE3','#5390D9',
]
function catColor(cat, map) {
  if (!cat) return '#7A7A7A'
  if (!map.current[cat]) {
    map.current[cat] = PALETTE[Object.keys(map.current).length % PALETTE.length]
  }
  return map.current[cat]
}
function truncate(s, n) { return !s ? '' : s.length > n ? s.slice(0, n) + '…' : s }

/* ── component ───────────────────────────────────────────────────── */
export default function ScholarGraph() {
  const [query, setQuery] = useState('')
  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [paperCount, setPaperCount] = useState(0)
  const [hotKeywords, setHotKeywords] = useState([])
  const [scholarRating, setScholarRating] = useState({ myScore: 0, avgRating: 0, ratingCount: 0 })
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const graphRef = useRef()
  const containerRef = useRef()
  const catMap = useRef({})
  const [graphDims, setGraphDims] = useState({ w: 800, h: 560 })

  useEffect(() => {
    const measure = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect()
        setGraphDims({ w: rect.width, h: Math.max(500, window.innerHeight - 300) })
      }
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  // Fetch hot keywords on mount
  useEffect(() => {
    api.get('/api/scholars/hot-keywords')
      .then(res => setHotKeywords(res.data.keywords || []))
      .catch(() => {})
  }, [])

  const doSearch = async (searchQuery) => {
    if (!searchQuery.trim()) return null
    setQuery(searchQuery)
    setLoading(true); setSelected(null); setDetail(null)
    try {
      const res = await api.post('/api/scholars/graph', { query: searchQuery, topK: 60 })
      const d = res.data
      const gNodes = d.nodes.map(n => ({
        ...n,
        val: 3 + Math.sqrt(n.paperCount) * 4,
        color: catColor(n.category, catMap),
      }))
      setNodes(gNodes)
      setEdges(d.edges)
      setPaperCount(d.paperCount)
      setSearched(true)
      setTimeout(() => graphRef.current?.zoomToFit(400, 60), 600)
      return gNodes
    } catch (err) {
      alert(err.response?.data?.error || '搜索失败')
      return null
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = async (e) => {
    e.preventDefault()
    doSearch(query)
  }

  // Auto-search when navigated with ?author= param
  const autoSearchedRef = useRef(false)
  useEffect(() => {
    const authorParam = searchParams.get('author')
    if (authorParam && !autoSearchedRef.current) {
      autoSearchedRef.current = true
      ;(async () => {
        const gNodes = await doSearch(authorParam)
        if (gNodes) {
          const norm = (s) => s.toLowerCase().replace(/\s+/g, '')
          const target = gNodes.find(n => norm(n.name) === norm(authorParam))
            || gNodes.find(n => norm(n.name).includes(norm(authorParam)) || norm(authorParam).includes(norm(n.name)))
          if (target) {
            // slight delay to let graph render
            setTimeout(() => handleSelectScholar(target), 800)
          }
        }
        // Clear the param so refreshing doesn't re-trigger
        setSearchParams({}, { replace: true })
      })()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelectScholar = useCallback(async (scholar) => {
    if (selected?.id === scholar.id) {
      setSelected(null); setDetail(null); setScholarRating({ myScore: 0, avgRating: 0, ratingCount: 0 }); return
    }
    setSelected(scholar)
    setDetailLoading(true)
    try {
      const res = await api.get(`/api/scholars/detail/${encodeURIComponent(scholar.name)}`)
      setDetail(res.data)
      // Fetch my rating
      try {
        const rRes = await api.get(`/api/scholars/rate/${encodeURIComponent(scholar.name)}`)
        setScholarRating(rRes.data)
      } catch {
        setScholarRating({ myScore: 0, avgRating: res.data.avgRating || 0, ratingCount: res.data.ratingCount || 0 })
      }
    } catch {
      setDetail(null)
    } finally {
      setDetailLoading(false)
    }
  }, [selected])

  const handleRateScholar = async (score) => {
    if (!selected) return
    try {
      const res = await api.post('/api/scholars/rate', { name: selected.name, score })
      setScholarRating({ myScore: res.data.score, avgRating: res.data.avgRating, ratingCount: res.data.ratingCount })
    } catch { /* ignore */ }
  }

  /* ── graph painters ────────────────────────────────────────────── */
  const paintNode = useCallback((node, ctx, globalScale) => {
    const r = Math.sqrt(node.val) * 1.6
    const isSel = selected?.id === node.id

    // glow for selected
    if (isSel) {
      ctx.save()
      ctx.shadowColor = node.color
      ctx.shadowBlur = 16
      ctx.beginPath(); ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI)
      ctx.fillStyle = 'rgba(255,255,255,0.2)'; ctx.fill()
      ctx.restore()
    }

    // solid circle
    ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
    ctx.fillStyle = node.color; ctx.fill()
    ctx.strokeStyle = isSel ? '#FFD700' : 'rgba(0,0,0,0.1)'
    ctx.lineWidth = isSel ? 2.5 / globalScale : 0.5 / globalScale
    ctx.stroke()

    // paper count badge
    if (node.paperCount > 1 && globalScale > 0.3) {
      const badgeR = Math.max(5 / globalScale, 2)
      ctx.beginPath()
      ctx.arc(node.x + r * 0.7, node.y - r * 0.7, badgeR, 0, 2 * Math.PI)
      ctx.fillStyle = '#C0392B'; ctx.fill()
      const fs = Math.max(6 / globalScale, 1.8)
      ctx.font = `bold ${fs}px sans-serif`
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillStyle = '#fff'
      ctx.fillText(node.paperCount, node.x + r * 0.7, node.y - r * 0.7)
    }

    // name label
    if (globalScale > 0.4) {
      const fs = Math.max(10 / globalScale, 2.2)
      ctx.font = `500 ${fs}px -apple-system, sans-serif`
      ctx.textAlign = 'center'; ctx.textBaseline = 'top'
      ctx.fillStyle = 'rgba(255,255,255,0.5)'
      ctx.fillText(truncate(node.name, 20), node.x + 0.5, node.y + r + 3.5)
      ctx.fillStyle = '#1B1B1B'
      ctx.fillText(truncate(node.name, 20), node.x, node.y + r + 3)
    }
  }, [selected])

  const paintLink = useCallback((link, ctx, globalScale) => {
    if (!link.source.x) return
    const w = Math.min(0.5 + link.weight * 0.8, 4)
    const alpha = Math.min(0.1 + link.weight * 0.12, 0.6)
    ctx.beginPath()
    ctx.moveTo(link.source.x, link.source.y)
    ctx.lineTo(link.target.x, link.target.y)
    ctx.strokeStyle = `rgba(27,67,50,${alpha})`
    ctx.lineWidth = w / globalScale
    ctx.stroke()

    // weight label
    if (link.weight > 1 && globalScale > 0.7) {
      const mx = (link.source.x + link.target.x) / 2
      const my = (link.source.y + link.target.y) / 2
      const fs = Math.max(7 / globalScale, 1.8)
      ctx.font = `${fs}px sans-serif`
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillStyle = `rgba(45,106,79,${Math.min(alpha + 0.2, 0.8)})`
      ctx.fillText(`${link.weight}篇`, mx, my - 3 / globalScale)
    }
  }, [])

  /* derived */
  const categories = [...new Set(nodes.map(n => n.category).filter(Boolean))]

  // edges for selected node
  const selectedEdges = selected
    ? edges.filter(e => {
        const sid = typeof e.source === 'object' ? e.source.id : e.source
        const tid = typeof e.target === 'object' ? e.target.id : e.target
        return sid === selected.id || tid === selected.id
      })
    : []

  return (
    <div className="sg-page">
      {/* Hero */}
      <div className="sg-hero">
        <div className="sg-hero-inner">
          <h1>学术族谱</h1>
          <p className="sg-hero-sub">搜索研究方向 · 发现核心学者 · 探索合作关系</p>
          <form className="sg-search-form" onSubmit={handleSearch}>
            <div className="sg-input-wrap">
              <svg className="sg-search-svg" viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd"/>
              </svg>
              <input
                className="sg-input"
                type="text"
                placeholder="输入关键词或研究方向…"
                value={query}
                onChange={e => setQuery(e.target.value)}
                autoFocus
              />
            </div>
            <button className="sg-submit-btn" type="submit" disabled={loading}>
              {loading ? '搜索中…' : '搜索'}
            </button>
          </form>
        </div>
      </div>

      {/* Toolbar */}
      {searched && nodes.length > 0 && (
        <div className="sg-toolbar">
          <span className="sg-toolbar-info">
            共 <strong>{paperCount}</strong> 篇论文 ·{' '}
            <strong>{nodes.length}</strong> 位学者 ·{' '}
            <strong>{edges.length}</strong> 条合作关系
          </span>
        </div>
      )}

      {/* Empty states */}
      {!searched && !loading && (
        <div className="sg-empty">
          <div className="sg-empty-icon">
            <svg viewBox="0 0 80 80" fill="none" width="80" height="80">
              <circle cx="24" cy="28" r="7" fill="#52B788" opacity="0.6"/>
              <circle cx="56" cy="28" r="7" fill="#2D6A4F" opacity="0.5"/>
              <circle cx="40" cy="54" r="9" fill="#40916C" opacity="0.5"/>
              <line x1="30" y1="32" x2="35" y2="48" stroke="#95D5B2" strokeWidth="1.5" opacity="0.5"/>
              <line x1="50" y1="32" x2="45" y2="48" stroke="#95D5B2" strokeWidth="1.5" opacity="0.5"/>
              <line x1="31" y1="28" x2="49" y2="28" stroke="#95D5B2" strokeWidth="1.5" opacity="0.5"/>
            </svg>
          </div>
          <p className="sg-empty-text">输入研究方向，发现核心学者与合作关系</p>
          <p className="sg-empty-hint">系统将从论文库中挖掘作者合作网络</p>

          {/* Hot keywords */}
          {hotKeywords.length > 0 && (
            <div className="sg-hot-keywords">
              <p className="sg-hot-title">热门研究方向</p>
              <div className="sg-hot-chips">
                {hotKeywords.map((kw, i) => (
                  <span key={i} className="sg-hot-chip" onClick={() => doSearch(kw.label)}>
                    {kw.label}
                    <span className="chip-count">({kw.count})</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {loading && (
        <div className="sg-empty">
          <div className="sg-spinner" />
          <p className="sg-empty-text">正在分析学者网络…</p>
        </div>
      )}

      {searched && nodes.length === 0 && !loading && (
        <div className="sg-empty">
          <p style={{ fontSize: '2rem', marginBottom: 8 }}>📭</p>
          <p className="sg-empty-text">未找到相关学者</p>
          <p className="sg-empty-hint">请尝试其他研究方向或更宽泛的关键词</p>
        </div>
      )}

      {/* Graph + Detail */}
      {searched && nodes.length > 0 && (
        <div className="sg-graph-container">
          <div className="sg-graph-wrap" ref={containerRef}>
            <ForceGraph2D
              ref={graphRef}
              graphData={{ nodes, links: edges }}
              width={graphDims.w}
              height={graphDims.h}
              backgroundColor="rgba(0,0,0,0)"
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={(node, color, ctx) => {
                ctx.beginPath()
                ctx.arc(node.x, node.y, Math.sqrt(node.val) * 1.6 + 5, 0, 2 * Math.PI)
                ctx.fillStyle = color; ctx.fill()
              }}
              linkCanvasObject={paintLink}
              linkPointerAreaPaint={(link, color, ctx) => {
                if (!link.source.x) return
                ctx.beginPath()
                ctx.moveTo(link.source.x, link.source.y)
                ctx.lineTo(link.target.x, link.target.y)
                ctx.strokeStyle = color; ctx.lineWidth = 8; ctx.stroke()
              }}
              onNodeClick={(node) => handleSelectScholar(node)}
              onBackgroundClick={() => { setSelected(null); setDetail(null) }}
              cooldownTicks={120}
              d3AlphaDecay={0.025}
              d3VelocityDecay={0.3}
              enableNodeDrag
            />

            {/* Legend */}
            {categories.length > 0 && (
              <div className="sg-graph-legend">
                {categories.map(cat => (
                  <span key={cat} className="sg-legend-item">
                    <span className="sg-legend-dot" style={{ background: catColor(cat, catMap) }} />
                    {cat}
                  </span>
                ))}
                <span className="sg-legend-item">
                  <span className="sg-legend-dot" style={{ background: '#C0392B' }} />
                  论文数量
                </span>
              </div>
            )}
          </div>

          {/* Detail panel */}
          {selected && (
            <aside className="sg-detail">
              <button className="sg-detail-close" onClick={() => { setSelected(null); setDetail(null) }}>✕</button>

              <div className="sg-detail-header">
                <div className="sg-scholar-avatar" style={{ background: selected.color }}>
                  {(detail?.name || selected.name)[0]}
                </div>
                <div>
                  <h2 className="sg-detail-name">{detail?.name || selected.name}</h2>
                  <p className="sg-detail-stat">
                    {detail?.paperCount ?? selected.paperCount} 篇论文
                    {selected.category && <> · {selected.category}</>}
                  </p>
                </div>
              </div>

              {/* Scholar rating */}
              <div className="sg-detail-rating">
                <StarRating value={scholarRating.myScore} onChange={handleRateScholar} size={22} />
                <span className="sg-rating-info">
                  {scholarRating.avgRating > 0
                    ? `${scholarRating.avgRating} 分 · ${scholarRating.ratingCount} 人评`
                    : '暂无评分'}
                </span>
              </div>

              {selected.keywords?.length > 0 && (
                <div className="sg-detail-section">
                  <h4>研究关键词</h4>
                  <div className="sg-detail-tags">
                    {selected.keywords.map((kw, i) => (
                      <span key={i} className="sg-tag">{kw}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* Co-authors from edges */}
              {selectedEdges.length > 0 && (
                <div className="sg-detail-section">
                  <h4>合作学者 ({selectedEdges.length})</h4>
                  <ul className="sg-coauthor-list">
                    {selectedEdges.sort((a, b) => b.weight - a.weight).slice(0, 10).map((edge, i) => {
                      const sid = typeof edge.source === 'object' ? edge.source.id : edge.source
                      const tid = typeof edge.target === 'object' ? edge.target.id : edge.target
                      const coName = sid === selected.id ? tid : sid
                      const coNode = nodes.find(n => n.id === coName)
                      return (
                        <li key={i} className="sg-coauthor-item" onClick={() => {
                          if (coNode) handleSelectScholar(coNode)
                        }}>
                          <span className="sg-coauthor-name">{coName}</span>
                          <span className="sg-coauthor-count">合作 {edge.weight} 篇</span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}

              {/* Detailed info */}
              {detailLoading && <div className="sg-detail-loading">加载中…</div>}
              {detail && !detailLoading && (
                <>
                  {detail.categories?.length > 0 && (
                    <div className="sg-detail-section">
                      <h4>研究方向分布</h4>
                      <div className="sg-cat-bars">
                        {detail.categories.map((c, i) => (
                          <div key={i} className="sg-cat-bar">
                            <span className="sg-cat-name">{c.name}</span>
                            <div className="sg-bar-track">
                              <div className="sg-bar-fill" style={{
                                width: `${Math.min(100, (c.count / detail.paperCount) * 100)}%`,
                                background: catColor(c.name, catMap),
                              }} />
                            </div>
                            <span className="sg-cat-count">{c.count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {detail.papers?.length > 0 && (
                    <div className="sg-detail-section">
                      <h4>代表论文 ({detail.paperCount})</h4>
                      <ul className="sg-paper-list">
                        {detail.papers.slice(0, 8).map((p, i) => (
                          <li key={i} className="sg-paper-item"
                              onClick={() => navigate(`/paper/${p.articleNumber}`)}>
                            <span className="sg-paper-title">{truncate(p.title, 60)}</span>
                            {p.year && <span className="sg-paper-year">{p.year}</span>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </aside>
          )}
        </div>
      )}
    </div>
  )
}
