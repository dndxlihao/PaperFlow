import { useState, useEffect, useMemo, useRef } from 'react'
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom'
import api from '../api'
import StarRating from '../components/StarRating'
import PaperComments from '../components/PaperComments'
import getSourceInfo from '../utils/sourceInfo'
import { formatShanghaiDateTime } from '../utils/time'
import { normalizeSummaryHtml } from '../utils/summary'
import './PaperDetail.css'

// Sanitize HTML: only allow safe tags
function sanitizeHtml(html) {
  if (!html) return ''
  const div = document.createElement('div')
  div.innerHTML = html
  // Remove script/iframe/style tags
  div.querySelectorAll('script,iframe,style,link,object,embed').forEach(el => el.remove())
  return div.innerHTML
}

function stripHtmlToText(value) {
  if (!value) return ''
  const div = document.createElement('div')
  div.innerHTML = String(value)
  return (div.textContent || div.innerText || '').replace(/\s+\n/g, '\n').trim()
}

function resolveFigureUrl(figurePath) {
  if (!figurePath) return ''
  if (/^https?:\/\//i.test(figurePath)) return figurePath
  return `/api/figures/${figurePath}`
}

export default function PaperDetail() {
  const { articleNumber } = useParams()
  const nav = useNavigate()
  const location = useLocation()
  const [paper, setPaper] = useState(null)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [addMsg, setAddMsg] = useState('')
  const [myRating, setMyRating] = useState(null)
  const [avgRating, setAvgRating] = useState(null)
  const [ratingCount, setRatingCount] = useState(0)
  const [currentUser, setCurrentUser] = useState(null)
  const [editMode, setEditMode] = useState(false)
  const [submittingEdit, setSubmittingEdit] = useState(false)
  const [editError, setEditError] = useState('')
  const [editSuccess, setEditSuccess] = useState('')
  const [editHistory, setEditHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [historyFilter, setHistoryFilter] = useState('all')
  const [withdrawingRequestId, setWithdrawingRequestId] = useState(null)
  const [editFigureFile, setEditFigureFile] = useState(null)
  const [contextMenu, setContextMenu] = useState({
    visible: false,
    x: 0,
    y: 0,
    targetField: '',
    selectedText: '',
  })
  const summaryTextRef = useRef(null)
  const figureTextRef = useRef(null)
  const [editDraft, setEditDraft] = useState({
    summary: '',
    figureExplanation: '',
    figurePath: '',
    targetField: '',
    selectedText: '',
    suggestion: '',
    reason: '',
  })
  const filteredHistory = useMemo(() => {
    const items = editHistory || []
    if (historyFilter === 'all') return items
    if (historyFilter === 'mine') {
      if (!currentUser?.id) return []
      return items.filter(item => Number(item.userId) === Number(currentUser.id))
    }
    return items.filter(item => item.status === historyFilter)
  }, [editHistory, historyFilter, currentUser])

  const backInfo = useMemo(() => {
    const state = location.state || {}
    const returnTo = (typeof state.returnTo === 'string' && state.returnTo.startsWith('/'))
      ? state.returnTo
      : '/'
    const returnLabel = state.returnLabel || (returnTo.startsWith('/system-library') ? '返回系统论文库' : '返回首页')
    return { to: returnTo, label: returnLabel }
  }, [location.state])

  const trackSourceClick = (context = 'paper-detail') => {
    if (!articleNumber) return
    api.post(`/api/papers/${articleNumber}/source-click`, { context }).catch(() => {})
  }

  const syncEditDraftFromPaper = () => {
    setEditDraft({
      summary: '',
      figureExplanation: '',
      figurePath: '',
      targetField: '',
      selectedText: '',
      suggestion: '',
      reason: '',
    })
    setEditFigureFile(null)
  }

  const fetchEditHistory = async () => {
    if (!articleNumber) return
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const res = await api.get(`/api/papers/${articleNumber}/edit-requests`, {
        params: { limit: 80 },
      })
      setEditHistory(res.data.items || [])
    } catch (err) {
      setHistoryError(err.response?.data?.error || '编辑历史加载失败')
    } finally {
      setHistoryLoading(false)
    }
  }

  const openEditWorkspace = async () => {
    setEditMode(true)
    setEditError('')
    setEditSuccess('')
    if ((editHistory || []).length === 0 && !historyLoading) {
      await fetchEditHistory()
    }
  }

  const closeEditWorkspace = () => {
    setEditMode(false)
    setContextMenu(prev => ({ ...prev, visible: false }))
    setEditFigureFile(null)
  }

  const handleTextContextMenu = (event, targetField, containerRef) => {
    const selection = window.getSelection()
    const selectedText = (selection?.toString() || '').trim()
    if (!selectedText) return
    if (selectedText.length > 1500) return
    const range = selection?.rangeCount ? selection.getRangeAt(0) : null
    if (!range || !containerRef?.current) return
    const anchorNode = range.commonAncestorContainer
    if (!containerRef.current.contains(anchorNode)) return

    event.preventDefault()
    setContextMenu({
      visible: true,
      x: event.clientX,
      y: event.clientY,
      targetField,
      selectedText,
    })
  }

  const applySelectionAsSuggestion = async () => {
    if (!contextMenu.selectedText) return
    await openEditWorkspace()
    setEditDraft(prev => ({
      ...prev,
      targetField: contextMenu.targetField || prev.targetField,
      selectedText: contextMenu.selectedText,
    }))
    setContextMenu(prev => ({ ...prev, visible: false }))
  }

  useEffect(() => {
    const fetchPaper = async () => {
      let loadedPaper = null
      let loadedSummary = null
      try {
        try {
          const res = await api.get(`/api/papers/${articleNumber}`)
          if (res.data?.articleNumber) {
            loadedPaper = res.data
            setPaper(loadedPaper)
            if (loadedPaper.summary) {
              loadedSummary = {
                summary: loadedPaper.summary,
                generatedAt: loadedPaper.summaryGeneratedAt,
                summarySource: loadedPaper.summarySource || 'unknown',
              }
              setSummary(loadedSummary)
            }
            if (loadedPaper.avgRating != null) {
              setAvgRating(loadedPaper.avgRating)
              setRatingCount(loadedPaper.ratingCount || 0)
            }
            syncEditDraftFromPaper()
          } else {
            const fallback = await api.get('/api/papers', { params: { keyword: articleNumber, per_page: 1 } })
            const items = fallback.data.items || []
            if (items.length > 0) {
              loadedPaper = items[0]
              setPaper(loadedPaper)
              // If paper already has summary from backend, set it
              if (loadedPaper.summary) {
                loadedSummary = {
                  summary: loadedPaper.summary,
                  generatedAt: loadedPaper.summaryGeneratedAt,
                  summarySource: loadedPaper.summarySource || 'unknown',
                }
                setSummary(loadedSummary)
              }
              if (loadedPaper.avgRating != null) {
                setAvgRating(loadedPaper.avgRating)
                setRatingCount(loadedPaper.ratingCount || 0)
              }
              syncEditDraftFromPaper()
            }
          }
        } catch {
          try {
            const fallback = await api.get('/api/papers', { params: { keyword: articleNumber, per_page: 1 } })
            const items = fallback.data.items || []
            if (items.length > 0) {
              loadedPaper = items[0]
              setPaper(loadedPaper)
              if (loadedPaper.summary) {
                loadedSummary = {
                  summary: loadedPaper.summary,
                  generatedAt: loadedPaper.summaryGeneratedAt,
                  summarySource: loadedPaper.summarySource || 'unknown',
                }
                setSummary(loadedSummary)
              }
              if (loadedPaper.avgRating != null) {
                setAvgRating(loadedPaper.avgRating)
                setRatingCount(loadedPaper.ratingCount || 0)
              }
              syncEditDraftFromPaper()
            }
          } catch {}
        }

        // Try to get existing summary (may have more detail)
        try {
          const res = await api.get(`/api/papers/${articleNumber}/summary`)
          if (res.data?.summary) {
            loadedSummary = res.data
            setSummary(loadedSummary)
            syncEditDraftFromPaper()
          }
        } catch {}

        // Get my rating
        try {
          const res = await api.get(`/api/papers/${articleNumber}/rate`)
          setMyRating(res.data.myScore)
          if (res.data.avgRating != null) setAvgRating(res.data.avgRating)
          setRatingCount(res.data.ratingCount || 0)
        } catch {}

        // Current user info for "仅看我提交" filter.
        try {
          const me = await api.get('/api/auth/me')
          setCurrentUser(me.data || null)
        } catch {}
      } finally {
        // Keep detail page fast and resilient; edit history is lazy-loaded in annotation mode.
        setLoading(false)
      }
    }
    fetchPaper()
  }, [articleNumber])

  useEffect(() => {
    const query = new URLSearchParams(location.search || '')
    const openEdit = query.get('edit')
    if (openEdit === '1' || openEdit === 'true') {
      openEditWorkspace()
    }
  }, [location.search])

  useEffect(() => {
    if (!contextMenu.visible) return undefined
    const close = () => setContextMenu(prev => ({ ...prev, visible: false }))
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [contextMenu.visible])

  const handleToggleEditMode = () => {
    if (editMode) {
      closeEditWorkspace()
    } else {
      openEditWorkspace()
      syncEditDraftFromPaper()
    }
  }

  const handleWithdrawEditRequest = async (item) => {
    if (!paper?.articleNumber || !item?.id) return
    if (!window.confirm('确认撤销这条待审核申请吗？')) return
    setEditError('')
    setEditSuccess('')
    setWithdrawingRequestId(item.id)
    try {
      await api.delete(`/api/papers/${paper.articleNumber}/edit-requests/${item.id}`)
      setEditSuccess('已撤销该待审核申请')
      await fetchEditHistory()
    } catch (err) {
      setEditError(err.response?.data?.error || '撤销失败，请稍后重试')
    } finally {
      setWithdrawingRequestId(null)
    }
  }

  const submitEditRequest = async () => {
    if (!paper?.articleNumber) return
    const formData = new FormData()
    const summaryText = (editDraft.summary || '').trim()
    const figureExplanationText = (editDraft.figureExplanation || '').trim()
    const figurePathText = (editDraft.figurePath || '').trim()
    if (summaryText) formData.append('summary', summaryText)
    if (figureExplanationText) formData.append('figureExplanation', figureExplanationText)
    if (figurePathText) formData.append('figurePath', figurePathText)
    formData.append('targetField', (editDraft.targetField || '').trim())
    formData.append('selectedText', (editDraft.selectedText || '').trim())
    formData.append('suggestion', (editDraft.suggestion || '').trim())
    formData.append('reason', (editDraft.reason || '').trim())
    if (editFigureFile) {
      formData.append('figureImage', editFigureFile)
    }
    setEditError('')
    setEditSuccess('')
    setSubmittingEdit(true)
    try {
      await api.post(`/api/papers/${paper.articleNumber}/edit-requests`, formData)
      setEditSuccess('编辑申请已提交，等待管理员审核')
      setEditDraft(prev => ({
        ...prev,
        summary: '',
        figureExplanation: '',
        figurePath: '',
        suggestion: '',
        reason: '',
      }))
      setEditFigureFile(null)
      await fetchEditHistory()
      closeEditWorkspace()
    } catch (err) {
      setEditError(err.response?.data?.error || '提交编辑申请失败')
    } finally {
      setSubmittingEdit(false)
    }
  }

  const handleAddToLibrary = async () => {
    if (!paper) return
    setAddMsg('')
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
      setAddMsg('已加入')
    } catch {
      setAddMsg('添加失败')
    }
    setTimeout(() => setAddMsg(''), 3000)
  }

  const handleRate = async (score) => {
    try {
      const res = await api.post(`/api/papers/${articleNumber}/rate`, { score })
      setMyRating(score)
      setAvgRating(res.data.avgRating)
      setRatingCount(res.data.ratingCount)
    } catch {}
  }

  if (loading) return <div className="page-loading">加载中...</div>

  const summaryHtml = summary?.summary ? sanitizeHtml(normalizeSummaryHtml(summary.summary)) : ''
  const figureExplanationHtml = paper?.figureExplanation
    ? sanitizeHtml(normalizeSummaryHtml(paper.figureExplanation))
      .replace(/<p>\s*(?:　　|&emsp;&emsp;|&nbsp;&nbsp;)+/gi, '<p>')
    : ''
  const summarySourceLabel =
    summary?.summarySource === 'pdf_full_text'
      ? '基于 PDF 全文'
      : summary?.summarySource === 'abstract_only'
        ? '仅基于摘要'
        : summary?.summarySource === 'community_edit'
          ? '人工修订版（已审核）'
        : '来源未标注'
  const statusLabel = (status) => {
    if (status === 'approved') return '已通过'
    if (status === 'rejected') return '已拒绝'
    if (status === 'withdrawn') return '已撤销'
    return '审核中'
  }
  const targetFieldLabel = (field) => {
    if (field === 'summary') return 'AI 总结'
    if (field === 'figureExplanation') return 'AI 方法框架解读'
    if (field === 'figurePath') return '图片'
    return field || '未指定'
  }

  return (
    <div className="paper-detail">
      <Link to={backInfo.to} className="back-link">← {backInfo.label}</Link>

      {/* Source badge + keywords */}
      <div className="detail-source-row">
        {(() => {
          const src = getSourceInfo(paper || { articleNumber })
          return <span className={`source-badge ${src.cls}`}>{src.label}</span>
        })()}
        {paper?.category && <span className="category-badge">{paper.category}</span>}
        {summary && <span className="ai-done-badge">✨ AI 总结已生成</span>}
        <button
          type="button"
          className="btn btn-sm btn-outline detail-edit-toggle"
          onClick={handleToggleEditMode}
        >
          {editMode ? '收起编辑模式' : '✏️ 申请纠错'}
        </button>
      </div>

      <div className="detail-header">
        {paper?.titleZh && (
          <h1 className="title-zh">{paper.titleZh}</h1>
        )}
        <h2 className="title-en">{paper?.title || `论文 #${articleNumber}`}</h2>
        {paper?.authors?.length > 0 && (
          <div className="detail-authors-line">
            {(Array.isArray(paper.authors) ? paper.authors : [paper.authors]).map((a, i, arr) => (
              <span key={i}>
                <span className="detail-author-link" onClick={() => nav(`/scholars?author=${encodeURIComponent(a)}`)}>{a}</span>
                {i < arr.length - 1 && ', '}
              </span>
            ))}
          </div>
        )}
        {paper?.affiliations?.length > 0 && (
          <div className="detail-affiliations-line">
            {paper.affiliations.join(' · ')}
          </div>
        )}
        {paper?.publicationTitle && (
          <div className="detail-journal">{paper.publicationTitle}</div>
        )}
      </div>

      {/* Keywords */}
      {paper?.keywords?.length > 0 && (
        <div className="detail-keywords">
          {paper.keywords.map((kw, i) => (
            <span key={i} className="keyword-tag">{kw}</span>
          ))}
        </div>
      )}

      {/* Rating */}
      <div className="detail-rating">
        <span className="rating-label">论文评分：</span>
        <StarRating value={myRating} onChange={handleRate} />
        <span className="rating-info">
          {avgRating != null
            ? <>平均 <b>{avgRating}</b> 分 ({ratingCount} 人评分)</>
            : <span style={{color: '#bbb'}}>暂无评分</span>}
        </span>
      </div>

      {paper && (
        <div className="detail-meta">
          {paper.publicationDate && (
            <div className="meta-row meta-row-inline">
              <div className="meta-left"><span className="meta-icon">📅</span><strong>发表时间：</strong>{paper.publicationDate}</div>
              <div className="meta-inline-actions">
                <button className="meta-action-btn" onClick={handleAddToLibrary} disabled={!!addMsg}>
                  {addMsg || '加入论文库'}
                </button>
                {paper?.sourceUrl && (
                  <a
                    href={paper.sourceUrl}
                    className="meta-action-link"
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => trackSourceClick('paper-detail-meta')}
                  >
                    查看原文
                  </a>
                )}
                {paper?.title && (
                  <a
                    href={`https://scholar.google.com/scholar?q=${encodeURIComponent(paper.title)}`}
                    className="meta-action-link"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Google Scholar
                  </a>
                )}
              </div>
            </div>
          )}
          {paper.downloadCount != null && paper.downloadCount > 0 && (
            <div className="meta-row"><span className="meta-icon">⬇</span><strong>下载量：</strong>{paper.downloadCount}</div>
          )}
          {!paper.publicationDate && (
            <div className="meta-row meta-row-inline">
              <div className="meta-inline-actions">
                <button className="meta-action-btn" onClick={handleAddToLibrary} disabled={!!addMsg}>
                  {addMsg || '加入论文库'}
                </button>
                {paper?.sourceUrl && (
                  <a
                    href={paper.sourceUrl}
                    className="meta-action-link"
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => trackSourceClick('paper-detail-meta')}
                  >
                    查看原文
                  </a>
                )}
                {paper?.title && (
                  <a
                    href={`https://scholar.google.com/scholar?q=${encodeURIComponent(paper.title)}`}
                    className="meta-action-link"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Google Scholar
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {paper?.abstract && (
        <div className="detail-section">
          <h2>📄 摘要</h2>
          <p>{paper.abstract}</p>
        </div>
      )}

      {paper?.figurePath && (
        <div className="detail-section figure-section">
          <h2>🖼️ 论文概念图</h2>
          <div className="figure-container">
            <img src={resolveFigureUrl(paper.figurePath)} alt="论文概念图" />
          </div>
          {paper.figureExplanation && (
            <div className="figure-explanation">
              <div className="figure-explanation-header">
                <span className="figure-explanation-icon">🤖</span>
                <span>AI 方法框架解读</span>
              </div>
              <div
                className="figure-explanation-text"
                ref={figureTextRef}
                onContextMenu={e => handleTextContextMenu(e, 'figureExplanation', figureTextRef)}
                dangerouslySetInnerHTML={{ __html: figureExplanationHtml }}
              />
            </div>
          )}
        </div>
      )}

      <div className="detail-section summary-section">
        <div className="summary-header">
          <h2>🤖 DeepSeek AI 总结</h2>
        </div>
        {summary ? (
          <div className="summary-content">
            <div className="summary-header-bar">
              <span className="summary-label">DeepSeek 中文深度解读</span>
              <div className="summary-meta">
                <span className={`summary-source-badge source-${summary?.summarySource || 'unknown'}`}>{summarySourceLabel}</span>
                <span className="summary-word-count">{summary.summary?.length || 0} 字</span>
              </div>
            </div>
            <div
              className="summary-text"
              ref={summaryTextRef}
              onContextMenu={e => handleTextContextMenu(e, 'summary', summaryTextRef)}
              dangerouslySetInnerHTML={{ __html: summaryHtml }}
            />
            {summary.generatedAt && (
              <div className="summary-time">生成于 {formatShanghaiDateTime(summary.generatedAt)}</div>
            )}
          </div>
        ) : (
          <div className="summary-placeholder">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--accent-light)" strokeWidth="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
            <p>该论文总结由后台自动生成。若暂未显示，请稍后刷新页面。</p>
          </div>
        )}
      </div>

      {editMode && (
        <div className="edit-review-overlay">
          <div className="edit-review-shell">
            <div className="edit-review-head">
              <h2>✏️ 批注与修改建议</h2>
              <button type="button" className="btn btn-sm btn-outline" onClick={closeEditWorkspace}>关闭</button>
            </div>
            <div className="edit-review-layout">
              <div className="edit-history-pane">
                <div className="history-pane-head">
                  <h3>修改历史</h3>
                  <div className="history-filter-bar">
                    <button
                      type="button"
                      className={`history-filter-btn ${historyFilter === 'all' ? 'active' : ''}`}
                      onClick={() => setHistoryFilter('all')}
                    >
                      全部
                    </button>
                    <button
                      type="button"
                      className={`history-filter-btn ${historyFilter === 'pending' ? 'active' : ''}`}
                      onClick={() => setHistoryFilter('pending')}
                    >
                      待审
                    </button>
                    <button
                      type="button"
                      className={`history-filter-btn ${historyFilter === 'approved' ? 'active' : ''}`}
                      onClick={() => setHistoryFilter('approved')}
                    >
                      通过
                    </button>
                    <button
                      type="button"
                      className={`history-filter-btn ${historyFilter === 'rejected' ? 'active' : ''}`}
                      onClick={() => setHistoryFilter('rejected')}
                    >
                      拒绝
                    </button>
                    <button
                      type="button"
                      className={`history-filter-btn ${historyFilter === 'withdrawn' ? 'active' : ''}`}
                      onClick={() => setHistoryFilter('withdrawn')}
                    >
                      撤销
                    </button>
                    <button
                      type="button"
                      className={`history-filter-btn ${historyFilter === 'mine' ? 'active' : ''}`}
                      onClick={() => setHistoryFilter('mine')}
                    >
                      我提交
                    </button>
                  </div>
                </div>
                {historyError && <div className="edit-request-error">{historyError}</div>}
                {historyLoading ? (
                  <div className="history-loading">历史记录加载中...</div>
                ) : filteredHistory.length === 0 ? (
                  <div className="history-empty">
                    {historyFilter === 'all' ? '暂时没有编辑记录' : '当前筛选条件下暂无记录'}
                  </div>
                ) : (
                  <div className="history-list">
                    {filteredHistory.map(item => (
                      <div className="history-item" key={item.id}>
                        <div className="history-item-head">
                          <div>
                            <b>{item.displayName || item.username || '用户'}</b>
                            {currentUser?.id && Number(item.userId) === Number(currentUser.id) && (
                              <span className="history-self-badge">我</span>
                            )}
                            <span className="history-item-meta"> 提交于 {formatShanghaiDateTime(item.createdAt)}</span>
                          </div>
                          <div className="history-item-head-actions">
                            <span className={`history-status status-${item.status}`}>{statusLabel(item.status)}</span>
                            {item.status === 'pending' && currentUser?.id && Number(item.userId) === Number(currentUser.id) && (
                              <button
                                type="button"
                                className="btn btn-sm btn-outline history-withdraw-btn"
                                disabled={withdrawingRequestId === item.id}
                                onClick={() => handleWithdrawEditRequest(item)}
                              >
                                {withdrawingRequestId === item.id ? '撤销中...' : '撤销'}
                              </button>
                            )}
                          </div>
                        </div>
                        {item.reason && <div className="history-reason">理由：{item.reason}</div>}
                        <details className="history-changes">
                          <summary>查看改动内容</summary>
                          {(item?.suggestionText || item?.selectedText) && (
                            <div className="history-change-block">
                              <div className="history-change-title">批注建议</div>
                              {item?.targetField && (
                                <div className="history-before">位置：{targetFieldLabel(item.targetField)}</div>
                              )}
                              {item?.selectedText && (
                                <div className="history-before">选中文本：{item.selectedText}</div>
                              )}
                              {item?.suggestionText && (
                                <div className="history-after">建议内容：{item.suggestionText}</div>
                              )}
                            </div>
                          )}
                          {item?.changes?.figureExplanation?.to && (
                            <div className="history-change-block">
                              <div className="history-change-title">AI 方法框架解读</div>
                              <div className="history-before">原文：{stripHtmlToText(item.changes.figureExplanation.from) || '（空）'}</div>
                              <div className="history-after">修订：{stripHtmlToText(item.changes.figureExplanation.to) || '（空）'}</div>
                            </div>
                          )}
                          {item?.changes?.summary?.to && (
                            <div className="history-change-block">
                              <div className="history-change-title">AI 总结</div>
                              <div className="history-before">原文：{stripHtmlToText(item.changes.summary.from) || '（空）'}</div>
                              <div className="history-after">修订：{stripHtmlToText(item.changes.summary.to) || '（空）'}</div>
                            </div>
                          )}
                          {item?.changes?.figurePath?.to && (
                            <div className="history-change-block">
                              <div className="history-change-title">图片修订</div>
                              <div className="history-before">原值：{item.changes.figurePath.from || '（空）'}</div>
                              <div className="history-after">修订：{item.changes.figurePath.to || '（空）'}</div>
                              <div className="history-image-preview">
                                <a
                                  href={resolveFigureUrl(item.changes.figurePath.to)}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  查看修订图片
                                </a>
                                <img src={resolveFigureUrl(item.changes.figurePath.to)} alt="修订图片预览" />
                              </div>
                            </div>
                          )}
                        </details>
                        {(item.reviewedAt || item.adminNote) && (
                          <div className="history-review">
                            审核：{item.reviewerName || '管理员'} · {item.reviewedAt ? formatShanghaiDateTime(item.reviewedAt) : '—'}
                            {item.adminNote ? ` · 备注：${item.adminNote}` : ''}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="edit-request-pane">
                <h3>提交修改意见</h3>
                {editSuccess && <div className="edit-request-success">{editSuccess}</div>}
                {editError && <div className="edit-request-error">{editError}</div>}
                <div className="edit-request-form">
                  <label>
                    <span>建议对应位置</span>
                    <select
                      value={editDraft.targetField}
                      onChange={e => setEditDraft(prev => ({ ...prev, targetField: e.target.value }))}
                    >
                      <option value="">未指定</option>
                      <option value="summary">AI 总结</option>
                      <option value="figureExplanation">AI 方法框架解读</option>
                      <option value="figurePath">图片</option>
                    </select>
                  </label>
                  <label>
                    <span>选中文本（可从正文右键“添加修改建议”自动带入）</span>
                    <textarea
                      value={editDraft.selectedText}
                      onChange={e => setEditDraft(prev => ({ ...prev, selectedText: e.target.value }))}
                      rows={4}
                      maxLength={2000}
                      placeholder="建议先在正文中鼠标选中一段文字后右键添加"
                    />
                  </label>
                  <label>
                    <span>修改建议（必填）</span>
                    <textarea
                      value={editDraft.suggestion}
                      onChange={e => setEditDraft(prev => ({ ...prev, suggestion: e.target.value }))}
                      rows={5}
                      maxLength={4000}
                      placeholder="请描述错误点与建议修改内容..."
                    />
                  </label>
                  <label>
                    <span>补充说明（可选）</span>
                    <textarea
                      value={editDraft.reason}
                      onChange={e => setEditDraft(prev => ({ ...prev, reason: e.target.value }))}
                      rows={3}
                      maxLength={2000}
                      placeholder="可写参考依据、上下文等..."
                    />
                  </label>
                  <details>
                    <summary>可选：直接给出替换后的完整文本</summary>
                    <label>
                      <span>修订后的 AI 方法框架解读（可选）</span>
                      <textarea
                        value={editDraft.figureExplanation}
                        onChange={e => setEditDraft(prev => ({ ...prev, figureExplanation: e.target.value }))}
                        rows={6}
                        maxLength={12000}
                      />
                    </label>
                    <label>
                      <span>修订后的 AI 总结（可选）</span>
                      <textarea
                        value={editDraft.summary}
                        onChange={e => setEditDraft(prev => ({ ...prev, summary: e.target.value }))}
                        rows={8}
                        maxLength={30000}
                      />
                    </label>
                    <label>
                      <span>修订后的图片（本地上传，可选）</span>
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/jpg,image/gif,image/webp"
                        onChange={(e) => {
                          const file = e.target.files?.[0] || null
                          setEditFigureFile(file)
                          if (file && !editDraft.targetField) {
                            setEditDraft(prev => ({ ...prev, targetField: 'figurePath' }))
                          }
                        }}
                      />
                      {editFigureFile ? (
                        <span>已选择：{editFigureFile.name}</span>
                      ) : (
                        <span>支持 png/jpg/jpeg/gif/webp，最大 8MB</span>
                      )}
                    </label>
                  </details>
                  <div className="edit-request-actions">
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      disabled={submittingEdit}
                      onClick={submitEditRequest}
                    >
                      {submittingEdit ? '提交中...' : '提交审核'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-outline"
                      disabled={submittingEdit}
                      onClick={closeEditWorkspace}
                    >
                      取消
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {contextMenu.visible && (
        <div
          className="annotation-context-menu"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={e => e.stopPropagation()}
        >
          <div className="annotation-context-preview">
            {(contextMenu.selectedText || '').slice(0, 90)}
            {(contextMenu.selectedText || '').length > 90 ? '...' : ''}
          </div>
          <button type="button" onClick={applySelectionAsSuggestion}>
            添加修改建议
          </button>
        </div>
      )}

      <div className="detail-section comments-section">
        <h2>💬 评论区</h2>
        <PaperComments articleNumber={articleNumber} />
      </div>

    </div>
  )
}
