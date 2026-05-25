import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import PaperCard from '../components/PaperCard'
import PaperComments from '../components/PaperComments'
import getSourceInfo from '../utils/sourceInfo'
import './Recommendations.css'

export default function Recommendations() {
  const [items, setItems] = useState([])
  const [dates, setDates] = useState([])
  const [selectedDate, setSelectedDate] = useState('')
  const [loading, setLoading] = useState(true)
  const [viewMode, setViewMode] = useState('grid') // 'grid' or 'list'
  const navigate = useNavigate()
  const sortedDates = [...dates].sort((a, b) => b.localeCompare(a))
  const earliestDate = sortedDates[sortedDates.length - 1] || ''
  const latestDate = sortedDates[0] || ''

  const trackSourceClick = (articleNumber, context = 'recommendations') => {
    if (!articleNumber) return
    api.post(`/api/papers/${articleNumber}/source-click`, { context }).catch(() => {})
  }

  const trackCardClick = (articleNumber, context = 'recommendations-card') => {
    if (!articleNumber) return
    api.post(`/api/papers/${articleNumber}/card-click`, { context }).catch(() => {})
  }

  const fetchDates = async () => {
    try {
      const res = await api.get('/api/recommend/dates')
      setDates(res.data || [])
    } catch {}
  }

  const fetchRecommendations = async (date) => {
    setLoading(true)
    try {
      const params = date ? { date } : {}
      const res = await api.get('/api/recommend', { params })
      setItems(res.data.items || [])
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDates()
    fetchRecommendations()
  }, [])

  const handleDateChange = (date) => {
    setSelectedDate(date)
    fetchRecommendations(date)
  }

  const handleCalendarChange = (e) => {
    const date = e.target.value
    if (date && !dates.includes(date)) {
      alert('该日期暂无推荐记录')
      return
    }
    handleDateChange(date)
  }

  const handleAddToLibrary = async (paper) => {
    try {
      await api.post('/api/library', {
        articleNumber: paper.articleNumber,
        title: paper.title,
        authors: paper.authors,
        abstract: paper.abstract,
        publicationDate: paper.publicationDate,
        publicationTitle: paper.publicationTitle,
        downloadCount: paper.downloadCount,
      })
      alert('已添加到论文库！')
    } catch (err) {
      alert(err.response?.data?.error || '添加失败')
    }
  }

  return (
    <div className="recommendations-page">
      <div className="page-header">
        <h1>每日好文推荐</h1>
      </div>

      <div className="date-filter">
        <button
          className={`date-tag ${!selectedDate ? 'active' : ''}`}
          onClick={() => handleDateChange('')}
        >
          全部
        </button>
        <div className="date-calendar-box">
          <input
            id="recommend-date"
            className="date-calendar-input"
            type="date"
            value={selectedDate}
            min={earliestDate || undefined}
            max={latestDate || undefined}
            onChange={handleCalendarChange}
          />
        </div>
        {selectedDate && <span className="date-selected-badge">当前: {selectedDate}</span>}
        {sortedDates.length > 0 && (
          <span className="date-range-hint">可选推荐日期: {earliestDate} 至 {latestDate}</span>
        )}
      </div>

      {loading ? (
        <div className="page-loading">加载中...</div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--accent-light)" strokeWidth="1.5"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          </div>
          <p>暂无推荐</p>
          <p className="empty-hint">当前日期暂无记录，可切换日期查看历史推荐</p>
        </div>
      ) : (
        <>
          <div className="results-toolbar">
            <span className="results-count">共 {items.length} 篇推荐论文</span>
            <div className="view-toggle">
              <button className={`toggle-btn ${viewMode === 'grid' ? 'active' : ''}`} onClick={() => setViewMode('grid')} title="卡片视图">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
              </button>
              <button className={`toggle-btn ${viewMode === 'list' ? 'active' : ''}`} onClick={() => setViewMode('list')} title="列表视图">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
              </button>
            </div>
          </div>

          {viewMode === 'grid' ? (
            <div className="rec-grid">
              {items.map(paper => {
                const badge = getSourceInfo(paper)
                return (
                  <div
                    key={paper.articleNumber}
                    className="rec-card"
                    onClick={() => {
                      trackCardClick(paper.articleNumber, 'recommendations-card')
                      navigate(`/paper/${paper.articleNumber}`)
                    }}
                  >
                    <div className="rec-card-top">
                      <span className={`source-badge ${badge.cls}`}>{badge.label}</span>
                      {paper.category && <span className="rec-category">{paper.category}</span>}
                      {paper.summary && <span className="ai-badge">AI ✓</span>}
                      {paper.avgRating != null && <span className="rec-rating">★ {paper.avgRating}</span>}
                    </div>
                    <h3 className="rec-card-title">{paper.title || '无标题'}</h3>
                    {paper.keywords?.length > 0 && (
                      <div className="rec-card-keywords">
                        {paper.keywords.map((kw, i) => (
                          <span key={i} className="rec-keyword">{kw}</span>
                        ))}
                      </div>
                    )}
                    <p className="rec-card-authors">
                      {Array.isArray(paper.authors)
                        ? paper.authors.slice(0, 3).join(', ') + (paper.authors.length > 3 ? ' et al.' : '')
                        : ''}
                    </p>
                    <p className="rec-card-abstract">
                      {paper.abstract ? paper.abstract.slice(0, 150) + '...' : '暂无摘要'}
                    </p>
                    {paper.figurePath && (
                      <div className="rec-card-figure">
                        <img src={`/api/figures/${paper.figurePath}`} alt="论文插图" loading="lazy" />
                      </div>
                    )}
                    <div className="rec-card-footer">
                      <span>{paper.publicationDate || ''}</span>
                      <div className="rec-card-links">
                        {paper.sourceUrl && (
                          <a
                            href={paper.sourceUrl}
                            className="rec-source-link"
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={e => {
                              e.stopPropagation()
                              trackSourceClick(paper.articleNumber, 'recommendations-card')
                            }}
                          >
                            🔗 原文
                          </a>
                        )}
                        {paper.title && (
                          <a
                            href={`https://scholar.google.com/scholar?q=${encodeURIComponent(paper.title)}`}
                            className="rec-source-link"
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={e => e.stopPropagation()}
                          >
                            📚 搜索
                          </a>
                        )}
                        <span className="rec-card-link">查看详情 →</span>
                      </div>
                    </div>
                    <div onClick={e => e.stopPropagation()}>
                      <PaperComments articleNumber={paper.articleNumber} />
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            items.map(paper => (
              <PaperCard
                key={paper.articleNumber}
                paper={paper}
                actions={
                  <button className="btn btn-sm btn-outline" onClick={() => handleAddToLibrary(paper)}>
                    加入论文库
                  </button>
                }
              />
            ))
          )}
        </>
      )}
    </div>
  )
}
