import { useState } from 'react'
import api from '../api'
import PaperCard from '../components/PaperCard'
import './IEEESearch.css'

const TABS = [
  { key: 'ieee', label: 'IEEE' },
  { key: 'arxiv', label: 'arXiv' },
  { key: 'elsevier', label: 'Elsevier' },
]

const IEEE_JOURNALS = [
  { punumber: '59', name: 'Trans. Power Systems' },
  { punumber: '61', name: 'Trans. Power Electronics' },
  { punumber: '60', name: 'Trans. Power Delivery' },
  { punumber: '41', name: 'Trans. Industrial Electronics' },
  { punumber: '28', name: 'Trans. Energy Conversion' },
  { punumber: '5165411', name: 'Trans. Sustainable Energy' },
]

const ARXIV_CATEGORIES = [
  { value: '', label: '全部类别' },
  { value: 'cs.AI', label: 'cs.AI - 人工智能' },
  { value: 'cs.LG', label: 'cs.LG - 机器学习' },
  { value: 'cs.CV', label: 'cs.CV - 计算机视觉' },
  { value: 'cs.CL', label: 'cs.CL - 计算语言学' },
  { value: 'cs.CR', label: 'cs.CR - 密码与安全' },
  { value: 'cs.DS', label: 'cs.DS - 数据结构' },
  { value: 'cs.DB', label: 'cs.DB - 数据库' },
  { value: 'cs.IR', label: 'cs.IR - 信息检索' },
  { value: 'cs.SE', label: 'cs.SE - 软件工程' },
  { value: 'cs.NE', label: 'cs.NE - 神经进化' },
  { value: 'cs.RO', label: 'cs.RO - 机器人学' },
  { value: 'stat.ML', label: 'stat.ML - 统计机器学习' },
  { value: 'eess.SP', label: 'eess.SP - 信号处理' },
  { value: 'eess.SY', label: 'eess.SY - 系统与控制' },
]

export default function IEEESearch() {
  const [activeTab, setActiveTab] = useState('ieee')
  // IEEE
  const [punumber, setPunumber] = useState('')
  const [isnumber, setIsnumber] = useState('')
  const [sortType, setSortType] = useState('paper-citations')
  // arXiv
  const [arxivQuery, setArxivQuery] = useState('')
  const [arxivCategory, setArxivCategory] = useState('')
  const [arxivMaxResults, setArxivMaxResults] = useState('25')
  // Elsevier
  const [elsevierQuery, setElsevierQuery] = useState('')
  const [elsevierMaxResults, setElsevierMaxResults] = useState('25')
  // common
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleIEEESearch = async (e) => {
    e.preventDefault()
    if (!punumber || !isnumber) { setError('请填写 PU Number 和 IS Number'); return }
    setError(''); setLoading(true)
    try {
      const res = await api.get('/api/ieee', {
        params: { punumber, isnumber, sortType, start_page: 1, end_page: 1, len: 25 }
      })
      setResults(res.data || [])
    } catch (err) {
      setError(err.response?.data?.error || '搜索失败'); setResults([])
    } finally { setLoading(false) }
  }

  const handleArxivSearch = async (e) => {
    e.preventDefault()
    if (!arxivQuery.trim()) { setError('请输入搜索关键词'); return }
    setError(''); setLoading(true)
    try {
      const res = await api.get('/api/arxiv', {
        params: { query: arxivQuery, category: arxivCategory, max_results: arxivMaxResults }
      })
      setResults(res.data || [])
    } catch (err) {
      setError(err.response?.data?.error || '搜索失败'); setResults([])
    } finally { setLoading(false) }
  }

  const handleElsevierSearch = async (e) => {
    e.preventDefault()
    if (!elsevierQuery.trim()) { setError('请输入搜索关键词'); return }
    setError(''); setLoading(true)
    try {
      const res = await api.get('/api/elsevier', {
        params: { query: elsevierQuery, max_results: elsevierMaxResults }
      })
      setResults(res.data || [])
    } catch (err) {
      setError(err.response?.data?.error || '搜索失败'); setResults([])
    } finally { setLoading(false) }
  }

  const handleAddToLibrary = async (item) => {
    try {
      await api.post('/api/library', {
        articleNumber: item.articleNumber,
        title: item.articleTitle || item.title,
        authors: item.authors,
        abstract: item.abstract,
        publicationDate: item.publicationDate,
        publicationTitle: item.publicationTitle || item.displayPublicationTitle,
        downloadCount: item.downloadCount,
      })
      alert('已添加到论文库！')
    } catch (err) { alert(err.response?.data?.error || '添加失败') }
  }

  const handleImportAndSummarize = async (item) => {
    try {
      await api.post('/api/papers/import', {
        articleNumber: item.articleNumber,
        title: item.articleTitle || item.title,
        authors: item.authors,
        abstract: item.abstract,
        publicationDate: item.publicationDate,
        publicationTitle: item.publicationTitle || item.displayPublicationTitle,
        downloadCount: item.downloadCount,
      })
      window.location.href = `/paper/${item.articleNumber}`
    } catch (err) { alert(err.response?.data?.error || '导入失败') }
  }

  const switchTab = (key) => {
    setActiveTab(key)
    setResults([])
    setError('')
  }

  return (
    <div className="search-page">
      <h1>论文搜索</h1>

      <div className="source-tabs">
        {TABS.map(t => (
          <button
            key={t.key}
            className={`source-tab ${activeTab === t.key ? 'active' : ''}`}
            onClick={() => switchTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ---- IEEE ---- */}
      {activeTab === 'ieee' && (
        <>
          <div className="quick-sources">
            <span>快速选择期刊：</span>
            {IEEE_JOURNALS.map(s => (
              <button key={s.punumber} className={`source-tag ${punumber === s.punumber ? 'active' : ''}`}
                onClick={() => setPunumber(s.punumber)}>
                {s.name}
              </button>
            ))}
          </div>
          <form className="search-form" onSubmit={handleIEEESearch}>
            <div className="form-row">
              <div className="form-group">
                <label>PU Number</label>
                <input value={punumber} onChange={e => setPunumber(e.target.value)} placeholder="如: 59" />
              </div>
              <div className="form-group">
                <label>IS Number</label>
                <input value={isnumber} onChange={e => setIsnumber(e.target.value)} placeholder="如: 11345511" />
              </div>
              <div className="form-group">
                <label>排序方式</label>
                <select value={sortType} onChange={e => setSortType(e.target.value)}>
                  <option value="paper-citations">引用量</option>
                  <option value="newest">最新</option>
                  <option value="oldest">最早</option>
                </select>
              </div>
            </div>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? '搜索中...' : '搜索 IEEE'}
            </button>
          </form>
        </>
      )}

      {/* ---- arXiv ---- */}
      {activeTab === 'arxiv' && (
        <form className="search-form" onSubmit={handleArxivSearch}>
          <div className="form-row">
            <div className="form-group" style={{gridColumn:'span 2'}}>
              <label>搜索关键词</label>
              <input value={arxivQuery} onChange={e => setArxivQuery(e.target.value)}
                placeholder="如: transformer attention mechanism" />
            </div>
            <div className="form-group">
              <label>最大结果数</label>
              <select value={arxivMaxResults} onChange={e => setArxivMaxResults(e.target.value)}>
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="50">50</option>
              </select>
            </div>
          </div>
          <div className="form-row-2">
            <div className="form-group">
              <label>论文类别 (CCF-A 相关)</label>
              <select value={arxivCategory} onChange={e => setArxivCategory(e.target.value)}>
                {ARXIV_CATEGORIES.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>
            <div style={{display:'flex', alignItems:'flex-end'}}>
              <button type="submit" className="btn btn-primary" disabled={loading} style={{width:'100%'}}>
                {loading ? '搜索中...' : '搜索 arXiv'}
              </button>
            </div>
          </div>
        </form>
      )}

      {/* ---- Elsevier ---- */}
      {activeTab === 'elsevier' && (
        <form className="search-form" onSubmit={handleElsevierSearch}>
          <div className="form-row">
            <div className="form-group" style={{gridColumn:'span 2'}}>
              <label>搜索关键词</label>
              <input value={elsevierQuery} onChange={e => setElsevierQuery(e.target.value)}
                placeholder="如: deep learning energy systems" />
            </div>
            <div className="form-group">
              <label>最大结果数</label>
              <select value={elsevierMaxResults} onChange={e => setElsevierMaxResults(e.target.value)}>
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="50">50</option>
              </select>
            </div>
          </div>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? '搜索中...' : '搜索 Elsevier'}
          </button>
        </form>
      )}

      {error && <div className="search-error">{error}</div>}

      {results.length > 0 && (
        <div className="search-results">
          <div className="results-count">找到 {results.length} 篇论文</div>
          {results.map(item => (
            <PaperCard
              key={item.articleNumber}
              paper={{ ...item, title: item.articleTitle || item.title }}
              actions={
                <>
                  <button className="btn btn-sm btn-outline" onClick={() => handleAddToLibrary(item)}>
                    加入论文库
                  </button>
                  <button className="btn btn-sm btn-primary" onClick={() => handleImportAndSummarize(item)}>
                    查看详情 & AI总结
                  </button>
                </>
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}
