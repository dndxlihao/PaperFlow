import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import ForceGraph2D from 'react-force-graph-2d'
import api from '../api'
import './KnowledgeBase.css'

/* ── helpers ─────────────────────────────────────────────────────── */
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

const TOPIC_ICON_THEMES = [
  { key: 'rl', pattern: /(强化学习|reinforcement|marl|多智能体强化学习)/i, from: '#fef3c7', to: '#f59e0b', stroke: '#b45309' },
  { key: 'diffusion', pattern: /(扩散模型|diffusion|ddpm|score-based)/i, from: '#e0f2fe', to: '#0ea5e9', stroke: '#0369a1' },
  { key: 'gnn', pattern: /(图神经网络|graph neural|gnn|gcn|gat)/i, from: '#dcfce7', to: '#22c55e', stroke: '#15803d' },
  { key: 'transformer', pattern: /(transformer|attention|自注意力)/i, from: '#ffedd5', to: '#fb923c', stroke: '#c2410c' },
  { key: 'llm_rag', pattern: /(大语言模型.*rag|rag|检索增强)/i, from: '#ecfeff', to: '#06b6d4', stroke: '#0f766e' },
  { key: 'llm_agent', pattern: /(大语言模型.*智能体|智能体|agent|tool use|function call)/i, from: '#f5f3ff', to: '#a78bfa', stroke: '#6d28d9' },
  { key: 'llm_prompt', pattern: /(大语言模型.*提示工程|提示工程|prompt)/i, from: '#fdf2f8', to: '#f472b6', stroke: '#be185d' },
  { key: 'llm_reasoning', pattern: /(大语言模型.*推理增强|推理增强|reasoning|chain[-\s]?of[-\s]?thought)/i, from: '#eff6ff', to: '#60a5fa', stroke: '#1d4ed8' },
  { key: 'llm_finetune', pattern: /(大语言模型.*模型微调|模型微调|lora|sft|指令微调|量化|蒸馏|模型压缩)/i, from: '#fff7ed', to: '#fb923c', stroke: '#c2410c' },
  { key: 'llm', pattern: /(大语言模型|llm)/i, from: '#ede9fe', to: '#8b5cf6', stroke: '#6d28d9' },
  { key: 'control', pattern: /(模型预测控制|mpc|最优潮流|opf|优化)/i, from: '#ffe4e6', to: '#fb7185', stroke: '#be123c' },
  { key: 'v2g', pattern: /(车网互动|v2g|vehicle-to-grid)/i, from: '#cffafe', to: '#06b6d4', stroke: '#0e7490' },
  { key: 'smartgrid', pattern: /(智能电网|smart grid)/i, from: '#dcfce7', to: '#34d399', stroke: '#047857' },
  { key: 'microgrid', pattern: /(微电网|microgrid|配电网|distribution network)/i, from: '#ecfeff', to: '#22d3ee', stroke: '#0e7490' },
  { key: 'market', pattern: /(电力市场|power market|economic dispatch|经济调度)/i, from: '#fff1f2', to: '#fb7185', stroke: '#be123c' },
  { key: 'forecast', pattern: /(负荷预测|load forecasting|load prediction)/i, from: '#eef2ff', to: '#818cf8', stroke: '#4338ca' },
  { key: 'demand', pattern: /(需求响应|demand response)/i, from: '#fffbeb', to: '#facc15', stroke: '#a16207' },
  { key: 'stability', pattern: /(频率控制|暂态稳定|电压控制|状态估计)/i, from: '#f0fdf4', to: '#4ade80', stroke: '#166534' },
  { key: 'grid', pattern: /(电力系统|power system)/i, from: '#fef9c3', to: '#84cc16', stroke: '#4d7c0f' },
  { key: 'renewable', pattern: /(可再生能源|renewable|wind|solar|photovoltaic|光伏|风电)/i, from: '#dcfce7', to: '#22c55e', stroke: '#166534' },
  { key: 'storage', pattern: /(储能|battery|bess)/i, from: '#e0f2fe', to: '#38bdf8', stroke: '#075985' },
  { key: 'kg', pattern: /(知识图谱|knowledge graph)/i, from: '#fce7f3', to: '#ec4899', stroke: '#9d174d' },
]

function pickTopicTheme(topic, parentCategory) {
  const text = `${topic || ''} ${parentCategory || ''}`
  return TOPIC_ICON_THEMES.find(item => item.pattern.test(text)) || {
    key: 'default',
    from: '#f1f5f9',
    to: '#94a3b8',
    stroke: '#475569',
  }
}

function hashTopic(text = '') {
  let h = 0
  for (let i = 0; i < text.length; i += 1) {
    h = ((h << 5) - h + text.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

function TrendTopicIcon({ topic, parentCategory }) {
  const theme = pickTopicTheme(topic, parentCategory)
  const stroke = theme.stroke
  const common = { stroke, strokeWidth: 2, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' }
  const variant = hashTopic(`${theme.key}-${topic || ''}-${parentCategory || ''}`) % 4

  return (
    <svg viewBox="0 0 42 42" width="42" height="42" aria-hidden="true">
      <defs>
        <linearGradient id={`kb-topic-${theme.key}`} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={theme.from} />
          <stop offset="100%" stopColor={theme.to} />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="40" height="40" rx="12" fill={`url(#kb-topic-${theme.key})`} />

      {theme.key === 'rl' && (
        <>
          <circle cx="12" cy="21" r="3" {...common} />
          <circle cx="21" cy="13" r="3" {...common} />
          <circle cx="30" cy="21" r="3" {...common} />
          <path d="M15 20 L18.5 15.5 M23.5 15.5 L27 20 M15 22 L27 22" {...common} />
        </>
      )}
      {theme.key === 'diffusion' && (
        <>
          <circle cx="21" cy="21" r="4.5" {...common} />
          <circle cx="21" cy="21" r="9" {...common} opacity="0.9" />
          <circle cx="21" cy="21" r="13.5" {...common} opacity="0.8" />
        </>
      )}
      {theme.key === 'gnn' && (
        <>
          <circle cx="12" cy="13" r="2.8" {...common} />
          <circle cx="30" cy="13" r="2.8" {...common} />
          <circle cx="21" cy="21" r="2.8" {...common} />
          <circle cx="12" cy="29" r="2.8" {...common} />
          <circle cx="30" cy="29" r="2.8" {...common} />
          <path d="M14.5 14.5 L19 19 M28 14.5 L23 19 M14.5 27.5 L19 23 M28 27.5 L23 23 M14.5 13 H27.5 M14.5 29 H27.5" {...common} />
        </>
      )}
      {theme.key === 'llm' && (
        <>
          <rect x="11" y="11" width="20" height="20" rx="4" {...common} />
          <path d="M16 16 H26 M16 21 H26 M16 26 H22" {...common} />
          <path d="M9 17 H11 M9 25 H11 M31 17 H33 M31 25 H33" {...common} />
        </>
      )}
      {theme.key === 'llm_rag' && (
        <>
          <rect x="11" y="12" width="14" height="18" rx="2.5" {...common} />
          <path d="M14 17 H22 M14 21 H21 M14 25 H19" {...common} />
          <circle cx="29" cy="24" r="4" {...common} />
          <path d="M31.7 26.8 L34 29" {...common} />
        </>
      )}
      {theme.key === 'llm_agent' && (
        <>
          <circle cx="12" cy="21" r="2.6" {...common} />
          <circle cx="21" cy="12" r="2.6" {...common} />
          <circle cx="30" cy="21" r="2.6" {...common} />
          <circle cx="21" cy="30" r="2.6" {...common} />
          <circle cx="21" cy="21" r="2.8" {...common} />
          <path d="M14.5 20 L18.5 21 M23.5 21 L27.5 20 M21 14.8 L21 18.2 M21 23.8 L21 27.2" {...common} />
        </>
      )}
      {theme.key === 'llm_prompt' && (
        <>
          <path d="M11 15.5 C11 13.6 12.6 12 14.5 12 H27.5 C29.4 12 31 13.6 31 15.5 V23.5 C31 25.4 29.4 27 27.5 27 H19 L14 31 V27 H14.5 C12.6 27 11 25.4 11 23.5 Z" {...common} />
          <path d="M16 18 H26 M16 22 H23" {...common} />
        </>
      )}
      {theme.key === 'llm_reasoning' && (
        <>
          <circle cx="12.5" cy="15.5" r="2.3" {...common} />
          <circle cx="21" cy="21" r="2.3" {...common} />
          <circle cx="29.5" cy="27.5" r="2.3" {...common} />
          <path d="M14.5 16.8 L18.8 19.4 M23.2 22.2 L27.2 25.1 M29.5 25 V22.5 M29.5 25 H27" {...common} />
        </>
      )}
      {theme.key === 'llm_finetune' && (
        <>
          <path d="M13 13 V29 M21 13 V29 M29 13 V29" {...common} />
          <circle cx="13" cy="18" r="2.2" {...common} />
          <circle cx="21" cy="24" r="2.2" {...common} />
          <circle cx="29" cy="16" r="2.2" {...common} />
        </>
      )}
      {theme.key === 'transformer' && (
        <>
          <path d="M12 14 H30 M12 28 H30 M12 21 H30" {...common} />
          <path d="M16 14 V28 M21 14 V28 M26 14 V28" {...common} />
          <circle cx="21" cy="21" r="2.4" {...common} />
        </>
      )}
      {theme.key === 'control' && (
        <>
          <path d="M9 27 C13 12, 18 31, 23 16 C27 6, 30 23, 33 14" {...common} />
          <path d="M9 31 H33" {...common} opacity="0.8" />
          <circle cx="23" cy="16" r="2.2" {...common} />
        </>
      )}
      {theme.key === 'v2g' && (
        <>
          <rect x="9" y="19" width="18" height="8" rx="2" {...common} />
          <circle cx="13" cy="29.5" r="2" {...common} />
          <circle cx="23" cy="29.5" r="2" {...common} />
          <path d="M27 21 H32 V27 H27" {...common} />
          <path d="M30 13 L27 19 H30 L28 24" {...common} />
        </>
      )}
      {theme.key === 'grid' && (
        <>
          <path d="M21 10 L13 30 H29 Z" {...common} />
          <path d="M17 20 H25 M15 24 H27 M14 28 H28" {...common} />
          <path d="M21 10 V7 M18 7 H24" {...common} />
        </>
      )}
      {theme.key === 'smartgrid' && (
        <>
          <rect x="12" y="13" width="18" height="16" rx="3" {...common} />
          <circle cx="16" cy="17" r="1.6" {...common} />
          <circle cx="26" cy="17" r="1.6" {...common} />
          <circle cx="21" cy="24" r="1.6" {...common} />
          <path d="M17.5 17 H24.5 M17.2 18.1 L20 22.5 M24.8 18.1 L22 22.5" {...common} />
        </>
      )}
      {theme.key === 'microgrid' && (
        <>
          <circle cx="21" cy="21" r="9.2" {...common} />
          <circle cx="21" cy="12.5" r="1.8" {...common} />
          <circle cx="29" cy="21" r="1.8" {...common} />
          <circle cx="21" cy="29.5" r="1.8" {...common} />
          <circle cx="13" cy="21" r="1.8" {...common} />
          <path d="M21 14.3 V18 M24.8 21 H28 M21 24 V27.7 M14.9 21 H18" {...common} />
        </>
      )}
      {theme.key === 'market' && (
        <>
          <path d="M12 30 H30" {...common} />
          <rect x="13" y="22" width="3.8" height="8" {...common} />
          <rect x="19.1" y="18" width="3.8" height="12" {...common} />
          <rect x="25.2" y="14" width="3.8" height="16" {...common} />
        </>
      )}
      {theme.key === 'forecast' && (
        <>
          <path d="M12 29 H30 M12 29 V13" {...common} />
          <path d="M13.5 25 L18.5 21 L22.5 23 L28.5 16.5" {...common} />
          <circle cx="18.5" cy="21" r="1.4" {...common} />
          <circle cx="22.5" cy="23" r="1.4" {...common} />
          <circle cx="28.5" cy="16.5" r="1.4" {...common} />
        </>
      )}
      {theme.key === 'demand' && (
        <>
          <circle cx="21" cy="21" r="8.5" {...common} />
          <path d="M21 21 L24.8 18.3 M21 16 V12.8" {...common} />
          <path d="M14.5 30.5 L18 24 H15.5 L18.8 18.5" {...common} />
        </>
      )}
      {theme.key === 'stability' && (
        <>
          <path d="M10 22 C13 16, 16 28, 19 22 C22 16, 25 28, 28 22 C30 18, 31 20, 32 22" {...common} />
          <path d="M28.2 14.5 L30.5 16.6 L34 13.2" {...common} />
        </>
      )}
      {theme.key === 'storage' && (
        <>
          <rect x="11" y="14" width="20" height="14" rx="3" {...common} />
          <path d="M31 19 H33 V23 H31" {...common} />
          <path d="M15 21 H20 M22 21 H27" {...common} />
        </>
      )}
      {theme.key === 'renewable' && (
        <>
          <circle cx="21" cy="21" r="5.6" {...common} />
          <path d="M21 9 V13 M21 29 V33 M9 21 H13 M29 21 H33 M12.5 12.5 L15.5 15.5 M26.5 26.5 L29.5 29.5 M29.5 12.5 L26.5 15.5 M15.5 26.5 L12.5 29.5" {...common} />
        </>
      )}
      {theme.key === 'kg' && (
        <>
          <circle cx="12" cy="12" r="3" {...common} />
          <circle cx="30" cy="12" r="3" {...common} />
          <circle cx="21" cy="21" r="3" {...common} />
          <circle cx="12" cy="30" r="3" {...common} />
          <circle cx="30" cy="30" r="3" {...common} />
          <path d="M14 13.5 L19 19 M28 13.5 L23 19 M14 28.5 L19 23 M28 28.5 L23 23" {...common} />
        </>
      )}
      {theme.key === 'default' && (
        <>
          <circle cx="21" cy="21" r="8.5" {...common} />
          <path d="M21 12.5 V29.5 M12.5 21 H29.5" {...common} />
        </>
      )}

      {variant === 0 && <circle cx="33.5" cy="8.5" r="1.3" fill={stroke} opacity="0.85" />}
      {variant === 1 && <rect x="6.8" y="32" width="2.6" height="2.6" rx="0.6" fill={stroke} opacity="0.8" />}
      {variant === 2 && <path d="M7.8 9.8 L9.6 8 L11.4 9.8 L9.6 11.6 Z" fill={stroke} opacity="0.78" />}
      {variant === 3 && <path d="M32.4 33.2 L34 34.8 L35.6 33.2 L34 31.6 Z" fill={stroke} opacity="0.78" />}
    </svg>
  )
}

function buildSparklinePath(series = [], width = 220, height = 72, pad = 6) {
  if (!Array.isArray(series) || series.length === 0) return ''
  const max = Math.max(...series, 1)
  const min = Math.min(...series, 0)
  const span = Math.max(max - min, 1)
  const stepX = series.length > 1 ? (width - pad * 2) / (series.length - 1) : 0
  const points = series.map((v, i) => {
    const x = pad + i * stepX
    const y = height - pad - ((v - min) / span) * (height - pad * 2)
    return [x, y]
  })
  if (points.length === 0) return ''
  const head = points.map(([x, y], idx) => `${idx === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`).join(' ')
  return head
}

function formatRate(rate) {
  const n = Number(rate || 0)
  const pct = Math.abs(n) * 100
  if (n > 0) return `+${pct.toFixed(1)}%`
  if (n < 0) return `-${pct.toFixed(1)}%`
  return '0.0%'
}

function formatShanghaiDateTime(isoString) {
  if (!isoString) return ''
  try {
    return new Date(isoString).toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      hour12: false,
    })
  } catch {
    return ''
  }
}

/* ── component ───────────────────────────────────────────────────── */
export default function KnowledgeBase() {
  const [query, setQuery] = useState('')
  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])
  const [loading, setLoading] = useState(false)
  const [indexReady, setIndexReady] = useState(null)
  const [indexMeta, setIndexMeta] = useState(null)
  const [building, setBuilding] = useState(false)
  const [trendLoading, setTrendLoading] = useState(false)
  const [trendData, setTrendData] = useState({ months: [], categories: [] })
  const [publicationStatsLoading, setPublicationStatsLoading] = useState(false)
  const [publicationStats, setPublicationStats] = useState({
    journals: [],
    totalJournals: 0,
    totalPapersNonArxiv: 0,
    generatedAt: null,
  })
  const [selected, setSelected] = useState(null)
  const [searched, setSearched] = useState(false)
  const [viewMode, setViewMode] = useState('list')
  const navigate = useNavigate()
  const graphRef = useRef()
  const containerRef = useRef()
  const catMap = useRef({})
  const [graphDims, setGraphDims] = useState({ w: 800, h: 560 })

  const trackSourceClick = (articleNumber) => {
    if (!articleNumber) return
    api.post(`/api/papers/${articleNumber}/source-click`, { context: 'knowledge-base' }).catch(() => {})
  }

  /* measure graph container */
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
  }, [viewMode])

  const refreshIndexStatus = useCallback(() => {
    api.get('/api/knowledge/status')
      .then(r => {
        setIndexReady(!!r.data.ready)
        setIndexMeta(r.data || null)
      })
      .catch(() => setIndexReady(false))
  }, [])

  /* check index status */
  useEffect(() => {
    refreshIndexStatus()
  }, [refreshIndexStatus])

  useEffect(() => {
    let mounted = true
    const loadTrends = async () => {
      setTrendLoading(true)
      try {
        const res = await api.get('/api/knowledge/trends', {
          params: { months: 12, top: 6, experts: 5 },
        })
        if (mounted) {
          setTrendData(res.data || { months: [], categories: [] })
        }
      } catch {
        if (mounted) {
          setTrendData({ months: [], categories: [] })
        }
      } finally {
        if (mounted) setTrendLoading(false)
      }
    }
    loadTrends()
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    let mounted = true
    const loadPublicationStats = async () => {
      setPublicationStatsLoading(true)
      try {
        const res = await api.get('/api/knowledge/publication-stats')
        if (mounted) {
          setPublicationStats(res.data || {
            journals: [],
            totalJournals: 0,
            totalPapersNonArxiv: 0,
            generatedAt: null,
          })
        }
      } catch {
        if (mounted) {
          setPublicationStats({
            journals: [],
            totalJournals: 0,
            totalPapersNonArxiv: 0,
            generatedAt: null,
          })
        }
      } finally {
        if (mounted) setPublicationStatsLoading(false)
      }
    }
    loadPublicationStats()
    return () => { mounted = false }
  }, [])

  const handleBuildIndex = async () => {
    setBuilding(true)
    try {
      await api.post('/api/knowledge/build-index')
      await refreshIndexStatus()
    }
    catch { alert('索引构建失败') }
    finally { setBuilding(false) }
  }

  const performSearch = useCallback(async (rawQuery, options = {}) => {
    const keyword = (rawQuery || '').trim()
    if (!keyword) return
    const targetMode = options?.viewMode || viewMode
    if (options?.viewMode) setViewMode(options.viewMode)

    setLoading(true); setSelected(null)
    try {
      const res = await api.post('/api/knowledge/search', { query: keyword, topK: 40 })
      const d = res.data
      const gNodes = d.nodes.map(n => ({
        id: n.articleNumber, ...n,
        val: n.keywordHit ? 6 + n.score * 10 : 2 + n.score * 10,
        color: catColor(n.category, catMap),
      }))
      const gEdges = d.edges.map(e => ({
        source: e.source, target: e.target,
        similarity: e.similarity, label: e.label,
        sharedKeywords: e.sharedKeywords, weight: e.weight,
      }))
      setNodes(gNodes); setEdges(gEdges); setSearched(true)
      if (targetMode === 'graph') {
        setTimeout(() => graphRef.current?.zoomToFit(400, 60), 600)
      }
    } catch (err) { alert(err.response?.data?.error || '搜索失败') }
    finally { setLoading(false) }
  }, [viewMode])

  const handleSearch = async (e) => {
    e.preventDefault()
    await performSearch(query, { viewMode })
  }

  const handleTrendClick = async (item) => {
    const keyword = (item?.searchQuery || item?.topic || item?.category || '').trim()
    if (!keyword) return
    setQuery(keyword)
    await performSearch(keyword, { viewMode: 'list' })
  }

  /* ── graph painters ────────────────────────────────────────────── */
  const paintNode = useCallback((node, ctx, globalScale) => {
    const r = Math.sqrt(node.val) * 1.8
    const isSel = selected?.id === node.id

    // shadow for selected
    if (isSel) {
      ctx.save()
      ctx.shadowColor = node.color
      ctx.shadowBlur = 14
      ctx.beginPath(); ctx.arc(node.x, node.y, r + 2, 0, 2 * Math.PI)
      ctx.fillStyle = 'rgba(255,255,255,0.15)'; ctx.fill()
      ctx.restore()
    }

    // solid fill
    ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
    ctx.fillStyle = node.color; ctx.fill()
    ctx.strokeStyle = isSel ? '#1B4332' : 'rgba(0,0,0,0.08)'
    ctx.lineWidth = isSel ? 2 / globalScale : 0.5 / globalScale
    ctx.stroke()

    // keyword hit marker
    if (node.keywordHit) {
      ctx.font = `bold ${Math.max(8 / globalScale, 3)}px sans-serif`
      ctx.fillStyle = '#C0392B'
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillText('★', node.x + r * 0.7, node.y - r * 0.7)
    }

    // label
    if (globalScale > 0.5) {
      const fs = Math.max(10 / globalScale, 2.2)
      ctx.font = `500 ${fs}px Georgia, serif`
      ctx.textAlign = 'center'; ctx.textBaseline = 'top'
      ctx.fillStyle = 'rgba(255,255,255,0.55)'
      ctx.fillText(truncate(node.title, 16), node.x + 0.5, node.y + r + 3.5)
      ctx.fillStyle = '#1B1B1B'
      ctx.fillText(truncate(node.title, 16), node.x, node.y + r + 3)
    }
  }, [selected])

  const paintLink = useCallback((link, ctx, globalScale) => {
    if (!link.source.x) return
    const alpha = Math.min(0.08 + (link.similarity || 0) * 0.4, 0.45)
    ctx.beginPath()
    ctx.moveTo(link.source.x, link.source.y)
    ctx.lineTo(link.target.x, link.target.y)
    ctx.strokeStyle = `rgba(27,67,50, ${alpha})`
    ctx.lineWidth = 0.4 + (link.weight || 0) * 0.25
    ctx.stroke()

    if (link.label && globalScale > 0.9) {
      const mx = (link.source.x + link.target.x) / 2
      const my = (link.source.y + link.target.y) / 2
      const fs = Math.max(7 / globalScale, 1.8)
      ctx.save()
      const dx = link.target.x - link.source.x, dy = link.target.y - link.source.y
      const angle = Math.atan2(dy, dx)
      const flip = (angle > Math.PI / 2 || angle < -Math.PI / 2) ? angle + Math.PI : angle
      ctx.translate(mx, my); ctx.rotate(flip)
      ctx.font = `${fs}px -apple-system, sans-serif`
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillStyle = `rgba(45,106,79,${Math.min(alpha + 0.15, 0.7)})`
      ctx.fillText(link.label, 0, -3 / globalScale)
      ctx.restore()
    }
  }, [])

  /* ── derived ───────────────────────────────────────────────────── */
  const categories = [...new Set(nodes.map(n => n.category).filter(Boolean))]
  const kwCount = nodes.filter(n => n.keywordHit).length
  const trendCards = trendData?.categories || []
  const journalStats = publicationStats?.journals || []

  /* find edges for selected node */
  const selectedEdges = selected
    ? edges.filter(e => {
        const sid = typeof e.source === 'object' ? e.source.id : e.source
        const tid = typeof e.target === 'object' ? e.target.id : e.target
        return sid === selected.id || tid === selected.id
      })
    : []
  const relatedIds = new Set(selectedEdges.flatMap(e => {
    const sid = typeof e.source === 'object' ? e.source.id : e.source
    const tid = typeof e.target === 'object' ? e.target.id : e.target
    return [sid, tid]
  }))
  relatedIds.delete(selected?.id)

  return (
    <div className="kb-page">
      {/* ── Hero ──────────────────────────────────────────────────── */}
      <div className="kb-hero">
        <div className="kb-hero-inner">
          <h1>知识库</h1>
          <p className="kb-hero-sub">关键词 + 语义混合检索 · 知识图谱可视化</p>

          {indexReady === false && (
            <div className="kb-index-alert">
              <span>⚠ 尚未构建搜索索引</span>
              <button className="btn btn-sm" onClick={handleBuildIndex} disabled={building}
                style={{ background: '#fff', color: '#1B4332' }}>
                {building ? '构建中…' : '立即构建'}
              </button>
            </div>
          )}
          {indexMeta?.stale && (
            <div className="kb-index-alert">
              <span>
                ⚠ 当前索引与论文库不同步（已索引 {indexMeta.cachePaperCount || 0} / 数据库 {indexMeta.dbPaperCount || 0}）
              </span>
              <button className="btn btn-sm" onClick={handleBuildIndex} disabled={building}
                style={{ background: '#fff', color: '#1B4332' }}>
                {building ? '构建中…' : '立即同步'}
              </button>
            </div>
          )}

          <form className="kb-search-form" onSubmit={handleSearch}>
            <div className="kb-input-wrap">
              <svg className="kb-search-svg" viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd"/>
              </svg>
              <input
                className="kb-input"
                type="text"
                placeholder="输入关键词或研究方向…"
                value={query}
                onChange={e => setQuery(e.target.value)}
                autoFocus
              />
            </div>
            <button className="kb-submit-btn" type="submit" disabled={loading}>
              {loading ? '搜索中…' : '搜索'}
            </button>
          </form>
        </div>
      </div>

      {/* ── Toolbar ───────────────────────────────────────────────── */}
      {searched && nodes.length > 0 && (
        <div className="kb-toolbar">
          <span className="kb-toolbar-info">
            共 <strong>{nodes.length}</strong> 篇论文 · <strong>{edges.length}</strong> 条关联
            {kwCount > 0 && <> · <strong>{kwCount}</strong> 篇关键词命中</>}
          </span>
          <div className="kb-view-toggle">
            <button className={`kb-toggle-btn ${viewMode === 'list' ? 'active' : ''}`}
              onClick={() => setViewMode('list')}>
              <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15"><path fillRule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1V4zm0 6a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2zm0 6a1 1 0 011-1h12a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2z" clipRule="evenodd"/></svg>
              列表
            </button>
            <button className={`kb-toggle-btn ${viewMode === 'graph' ? 'active' : ''}`}
              onClick={() => { setViewMode('graph'); setTimeout(() => graphRef.current?.zoomToFit(400, 60), 300) }}>
              <svg viewBox="0 0 20 20" fill="currentColor" width="15" height="15"><path d="M13 7a3 3 0 11-6 0 3 3 0 016 0zM6 14a4 4 0 00-4 4h16a4 4 0 00-4-4H6z"/><circle cx="15" cy="6" r="2"/><circle cx="5" cy="6" r="2"/></svg>
              图谱
            </button>
          </div>
        </div>
      )}

      {/* ── Empty states ──────────────────────────────────────────── */}
      {!searched && !loading && (
        <div className="kb-empty kb-empty-with-trends">
          <div className="kb-empty-icon">
            <svg viewBox="0 0 80 80" fill="none" width="80" height="80">
              <circle cx="28" cy="32" r="8" fill="#95D5B2" opacity="0.6"/>
              <circle cx="52" cy="24" r="6" fill="#52B788" opacity="0.5"/>
              <circle cx="46" cy="50" r="10" fill="#2D6A4F" opacity="0.4"/>
              <line x1="34" y1="36" x2="47" y2="46" stroke="#40916C" strokeWidth="1.5" opacity="0.4"/>
              <line x1="33" y1="28" x2="48" y2="26" stroke="#40916C" strokeWidth="1.5" opacity="0.4"/>
            </svg>
          </div>
          <p className="kb-empty-text">输入关键词，探索论文知识图谱</p>
          <p className="kb-empty-hint">支持中英文关键词，系统将自动匹配标题、摘要和关键词</p>

          <section className="kb-trend-board">
            <div className="kb-trend-head">
              <h3>热点方向追踪</h3>
              <span>基于论文发表时间（近 12 个月）与专家活跃度</span>
            </div>
            {trendLoading ? (
              <div className="kb-trend-loading">趋势数据加载中...</div>
            ) : trendCards.length === 0 ? (
              <div className="kb-trend-loading">暂无趋势数据</div>
            ) : (
              <div className="kb-trend-grid">
                {trendCards.map((item, idx) => {
                  const topicName = item.topic || item.category
                  const path = buildSparklinePath(item.series, 220, 72, 7)
                  const trendUp = (item.growth3m || 0) >= 0
                  return (
                    <article
                      className="kb-trend-card kb-trend-clickable"
                      key={`${topicName}-${idx}`}
                      onClick={() => handleTrendClick(item)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(evt) => {
                        if (evt.key === 'Enter' || evt.key === ' ') {
                          evt.preventDefault()
                          handleTrendClick(item)
                        }
                      }}
                    >
                      <div className="kb-trend-card-top">
                        <div className="kb-trend-cover">
                          <TrendTopicIcon topic={topicName} parentCategory={item.parentCategory} />
                        </div>
                        <div className="kb-trend-main">
                          <h4>{topicName}</h4>
                          {item.parentCategory && item.parentCategory !== topicName && (
                            <div className="kb-trend-parent">主类目：{item.parentCategory}</div>
                          )}
                          <div className="kb-trend-metrics">
                            <span>近3月 {item.recent3m} 篇</span>
                            <span className={trendUp ? 'up' : 'down'}>
                              {trendUp ? '▲' : '▼'} {formatRate(item.growthRate3m)}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="kb-trend-chart">
                        <svg viewBox="0 0 220 72" preserveAspectRatio="none">
                          <defs>
                            <linearGradient id={`kbTrendGrad-${idx}`} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="rgba(87, 160, 93, 0.45)" />
                              <stop offset="100%" stopColor="rgba(87, 160, 93, 0.04)" />
                            </linearGradient>
                          </defs>
                          <rect x="0" y="0" width="220" height="72" fill="transparent" />
                          {path && (
                            <>
                              <path
                                d={`${path} L 213 65 L 7 65 Z`}
                                fill={`url(#kbTrendGrad-${idx})`}
                                stroke="none"
                              />
                              <path
                                d={path}
                                fill="none"
                                stroke="#2f7a4d"
                                strokeWidth="2.2"
                                strokeLinecap="round"
                              />
                            </>
                          )}
                        </svg>
                      </div>

                      <div className="kb-trend-foot">
                        <div className="kb-trend-total">窗口总量：{item.totalInWindow} 篇</div>
                        <div className="kb-trend-experts">
                          <span>资深专家：</span>
                          <div className="kb-trend-expert-list">
                            {(item.topExperts || []).slice(0, 4).map(expert => (
                              <button
                                key={expert.name}
                                type="button"
                                className="kb-trend-expert"
                                onClick={(evt) => {
                                  evt.stopPropagation()
                                  navigate(`/scholars?author=${encodeURIComponent(expert.name)}`)
                                }}
                              >
                                {expert.name} · {expert.paperCount}
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </section>

          <section className="kb-journal-board">
            <div className="kb-journal-head">
              <h3>期刊年份与 Issue 统计</h3>
              <span>仅统计系统论文库期刊论文（已排除 arXiv）</span>
            </div>
            {publicationStatsLoading ? (
              <div className="kb-trend-loading">统计数据加载中...</div>
            ) : journalStats.length === 0 ? (
              <div className="kb-trend-loading">暂无可展示的期刊统计</div>
            ) : (
              <>
                <div className="kb-journal-summary">
                  共收录 <strong>{publicationStats.totalJournals || 0}</strong> 本期刊，
                  非 arXiv 论文 <strong>{publicationStats.totalPapersNonArxiv || 0}</strong> 篇
                  {publicationStats.generatedAt && (
                    <span> · 更新于 {formatShanghaiDateTime(publicationStats.generatedAt)}</span>
                  )}
                </div>
                <div className="kb-journal-grid">
                  {journalStats.slice(0, 12).map((item) => (
                    <article key={item.journal} className="kb-journal-card">
                      <div className="kb-journal-card-head">
                        <h4>{item.journal}</h4>
                        <span>{item.paperCount} 篇</span>
                      </div>
                      <div className="kb-journal-years">
                        {(item.years || []).slice(0, 4).map((yearItem) => (
                          <div className="kb-journal-year-row" key={`${item.journal}-${yearItem.year}`}>
                            <div className="kb-journal-year-meta">
                              <strong>{yearItem.year}</strong>
                              <span>{yearItem.paperCount} 篇</span>
                            </div>
                            <div className="kb-journal-issue-list">
                              {(yearItem.issues || []).length > 0 ? (
                                yearItem.issues.slice(0, 6).map((issueItem) => (
                                  <span
                                    key={`${item.journal}-${yearItem.year}-${issueItem.issue}`}
                                    className="kb-journal-issue-tag"
                                  >
                                    {issueItem.issue.startsWith('M') ? `月份 ${issueItem.issue.slice(1)}` : `Issue ${issueItem.issue}`} · {issueItem.paperCount}
                                  </span>
                                ))
                              ) : (
                                <span className="kb-journal-issue-empty">Issue 未标注</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {loading && (
        <div className="kb-empty">
          <div className="kb-spinner" />
          <p className="kb-empty-text">正在搜索…</p>
        </div>
      )}

      {searched && nodes.length === 0 && !loading && (
        <div className="kb-empty">
          <p style={{ fontSize: '2rem', marginBottom: 8 }}>📭</p>
          <p className="kb-empty-text">未找到相关论文</p>
          <p className="kb-empty-hint">请尝试其他关键词或更宽泛的检索词</p>
        </div>
      )}

      {/* ── List view ─────────────────────────────────────────────── */}
      {searched && nodes.length > 0 && viewMode === 'list' && (
        <div className="kb-list-wrap">
          <div className="kb-card-list">
            {nodes.map((node, idx) => (
              <div
                key={node.articleNumber}
                className={`kb-card ${selected?.id === node.id ? 'kb-card-active' : ''}`}
                onClick={() => setSelected(prev => prev?.id === node.id ? null : node)}
              >
                <div className="kb-card-rank">#{idx + 1}</div>

                <div className="kb-card-body">
                  <div className="kb-card-top">
                    {node.keywordHit && <span className="kb-kw-badge">★ 关键词命中</span>}
                    {node.category && (
                      <span className="kb-cat-badge" style={{ color: node.color, borderColor: node.color }}>
                        {node.category}
                      </span>
                    )}
                    <span className="kb-score-badge">{(node.score * 100).toFixed(0)}%</span>
                  </div>

                  <h3 className="kb-card-title">{node.title}</h3>

                  <p className="kb-card-meta">
                    {node.authors?.slice(0, 3).join(', ')}{node.authors?.length > 3 ? ' 等' : ''}
                    {node.publicationDate && <> · {node.publicationDate}</>}
                  </p>

                  {node.abstract && (
                    <p className="kb-card-abstract">{truncate(node.abstract, 220)}</p>
                  )}
                  {node.relevanceReasons?.length > 0 && (
                    <p className="kb-card-explain">
                      {node.relevanceReasons.join(' · ')}
                    </p>
                  )}

                  {node.keywords?.length > 0 && (
                    <div className="kb-card-tags">
                      {node.keywords.slice(0, 6).map((kw, i) => (
                        <span key={i} className="kb-tag">{kw}</span>
                      ))}
                      {node.keywords.length > 6 && <span className="kb-tag kb-tag-more">+{node.keywords.length - 6}</span>}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* ── Detail panel ─────────────────────────────────────── */}
          {selected && (
            <aside className="kb-detail">
              <button className="kb-detail-close" onClick={() => setSelected(null)}>✕</button>

              {selected.figurePath && (
                <img className="kb-detail-fig" src={`/api/figures/${selected.figurePath}`} alt="" />
              )}

              <h2 className="kb-detail-title">{selected.title}</h2>

              <div className="kb-detail-badges">
                {selected.keywordHit && <span className="kb-kw-badge">★ 关键词命中</span>}
                {selected.category && (
                  <span className="kb-cat-badge" style={{ color: selected.color, borderColor: selected.color }}>
                    {selected.category}
                  </span>
                )}
                <span className="kb-score-badge">相关度 {(selected.score * 100).toFixed(0)}%</span>
              </div>
              {selected.relevanceReasons?.length > 0 && (
                <p className="kb-detail-explain">
                  <strong>命中解释：</strong>{selected.relevanceReasons.join(' · ')}
                </p>
              )}

              {selected.authors?.length > 0 && (
                <p className="kb-detail-meta">
                  <strong>作者：</strong>{selected.authors.slice(0, 5).join(', ')}{selected.authors.length > 5 ? ' 等' : ''}
                </p>
              )}
              {selected.publicationDate && (
                <p className="kb-detail-meta"><strong>日期：</strong>{selected.publicationDate}</p>
              )}

              {selected.abstract && (
                <div className="kb-detail-section">
                  <h4>摘要</h4>
                  <p>{selected.abstract}</p>
                </div>
              )}

              {selected.keywords?.length > 0 && (
                <div className="kb-detail-section">
                  <h4>关键词</h4>
                  <div className="kb-detail-tags">
                    {selected.keywords.map((kw, i) => <span key={i} className="kb-tag">{kw}</span>)}
                  </div>
                </div>
              )}

              {/* related papers via edges */}
              {relatedIds.size > 0 && (
                <div className="kb-detail-section">
                  <h4>关联论文 ({relatedIds.size})</h4>
                  <ul className="kb-related-list">
                    {[...relatedIds].slice(0, 8).map(rid => {
                      const rn = nodes.find(n => n.id === rid)
                      if (!rn) return null
                      const edge = selectedEdges.find(e => {
                        const s = typeof e.source === 'object' ? e.source.id : e.source
                        const t = typeof e.target === 'object' ? e.target.id : e.target
                        return (s === rid || t === rid)
                      })
                      return (
                        <li key={rid} className="kb-related-item" onClick={() => setSelected(rn)}>
                          <span className="kb-related-title">{truncate(rn.title, 50)}</span>
                          {edge?.label && <span className="kb-related-label">{edge.label}</span>}
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}

              <div className="kb-detail-actions">
                <button className="btn btn-primary" onClick={() => navigate(`/paper/${selected.articleNumber}`)}>
                  查看详情
                </button>
                {selected.sourceUrl && (
                  <a
                    className="btn btn-outline"
                    href={selected.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => trackSourceClick(selected.articleNumber)}
                  >
                    原文链接 ↗
                  </a>
                )}
              </div>
            </aside>
          )}
        </div>
      )}

      {/* ── Graph view ────────────────────────────────────────────── */}
      {searched && nodes.length > 0 && viewMode === 'graph' && (
        <div className="kb-graph-container">
          <div className="kb-graph-wrap" ref={containerRef}>
            <ForceGraph2D
              ref={graphRef}
              graphData={{ nodes, links: edges }}
              width={graphDims.w}
              height={graphDims.h}
              backgroundColor="rgba(0,0,0,0)"
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={(node, color, ctx) => {
                ctx.beginPath()
                ctx.arc(node.x, node.y, Math.sqrt(node.val) * 1.8 + 5, 0, 2 * Math.PI)
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
              onNodeClick={(node) => setSelected(prev => prev?.id === node.id ? null : node)}
              onBackgroundClick={() => setSelected(null)}
              cooldownTicks={100}
              d3AlphaDecay={0.03}
              d3VelocityDecay={0.25}
              enableNodeDrag
            />

            {/* Legend */}
            {categories.length > 0 && (
              <div className="kb-graph-legend">
                {categories.map(cat => (
                  <span key={cat} className="kb-legend-item">
                    <span className="kb-legend-dot" style={{ background: catColor(cat, catMap) }} />
                    {cat}
                  </span>
                ))}
                <span className="kb-legend-item">
                  <span style={{ color: '#C0392B', marginRight: 2, fontWeight: 700 }}>★</span>关键词命中
                </span>
              </div>
            )}
          </div>

          {/* Graph side detail */}
          {selected && (
            <aside className="kb-graph-detail">
              <button className="kb-detail-close" onClick={() => setSelected(null)}>✕</button>
              {selected.figurePath && (
                <img className="kb-detail-fig" src={`/api/figures/${selected.figurePath}`} alt="" />
              )}
              <h3 className="kb-detail-title">{selected.title}</h3>
              <div className="kb-detail-badges">
                {selected.keywordHit && <span className="kb-kw-badge">★ 关键词命中</span>}
                <span className="kb-score-badge">相关度 {(selected.score * 100).toFixed(0)}%</span>
              </div>
              {selected.relevanceReasons?.length > 0 && (
                <p className="kb-detail-explain">
                  <strong>命中解释：</strong>{selected.relevanceReasons.join(' · ')}
                </p>
              )}
              {selected.abstract && <p className="kb-graph-abstract">{truncate(selected.abstract, 280)}</p>}
              <button className="btn btn-primary btn-block" onClick={() => navigate(`/paper/${selected.articleNumber}`)}>
                查看详情
              </button>
            </aside>
          )}
        </div>
      )}
    </div>
  )
}
