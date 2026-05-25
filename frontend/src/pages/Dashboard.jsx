import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api'
import PaperComments from '../components/PaperComments'
import getSourceInfo from '../utils/sourceInfo'
import { formatShanghaiDateTime } from '../utils/time'
import './Dashboard.css'

const JOURNAL_OPTIONS = ['IEEE TSG', 'IEEE TSTE', 'IEEE TPWRS', 'IEEE TIE', 'Applied Energy', 'Energy']
const AREA_OPTIONS = ['电力系统', '新能源', '储能', '智能电网', '电力电子', '机器学习']

export default function Dashboard() {
  const [recommendations, setRecommendations] = useState([])
  const [stats, setStats] = useState({ libraryCount: 0, summaryCount: 0 })
  const [preferences, setPreferences] = useState({ journals: [], researchAreas: [] })
  const [showPrefEditor, setShowPrefEditor] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [customArea, setCustomArea] = useState('')
  const [channelSubscriptions, setChannelSubscriptions] = useState([])
  const [channelUpdates, setChannelUpdates] = useState([])
  const [channelRequests, setChannelRequests] = useState([])
  const [savingChannels, setSavingChannels] = useState(false)
  const [runningChannelMonitor, setRunningChannelMonitor] = useState(false)
  const [requestTitle, setRequestTitle] = useState('')
  const [requestDetail, setRequestDetail] = useState('')
  const [submittingRequest, setSubmittingRequest] = useState(false)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const recentShownRef = useRef([])

  const hasPreference = (preferences.journals?.length || 0) > 0 || (preferences.researchAreas?.length || 0) > 0

  const trackSourceClick = (articleNumber, context = 'dashboard') => {
    if (!articleNumber) return
    api.post(`/api/papers/${articleNumber}/source-click`, { context }).catch(() => {})
  }

  const trackCardClick = (articleNumber, context = 'dashboard-card') => {
    if (!articleNumber) return
    api.post(`/api/papers/${articleNumber}/card-click`, { context }).catch(() => {})
  }

  const loadRecommendations = async (refresh = false, excludeArticleNumbers = []) => {
    const params = { per_page: 10 }
    if (refresh) {
      params.refresh = 1
      params.seed = Date.now()
    }
    if (excludeArticleNumbers.length > 0) {
      params.exclude_article_numbers = excludeArticleNumbers.join(',')
    }
    const res = await api.get('/api/recommend/personalized', { params }).catch(() => ({ data: { items: [] } }))
    const items = res.data.items || []
    setRecommendations(items)
    const current = items.map(item => item.articleNumber).filter(Boolean)
    recentShownRef.current = Array.from(new Set([...recentShownRef.current, ...current])).slice(-40)
    if (res.data.preferences) {
      setPreferences(res.data.preferences)
    }
  }

  useEffect(() => {
    Promise.all([
      loadRecommendations(false),
      api.get('/api/library', { params: { per_page: 1 } }).catch(() => ({ data: { total: 0 } })),
      api.get('/api/stats').catch(() => ({ data: { summaryCount: 0 } })),
      api.get('/api/recommend/preferences').catch(() => ({ data: { journals: [], researchAreas: [] } })),
      api.get('/api/recommend/channels/subscriptions').catch(() => ({ data: { items: [] } })),
      api.get('/api/recommend/channels/updates', { params: { limit: 6, days: 30 } }).catch(() => ({ data: { items: [] } })),
      api.get('/api/recommend/channels/requests/mine').catch(() => ({ data: { items: [] } })),
    ]).then(([, libRes, statsRes, prefRes, subRes, updatesRes, reqRes]) => {
      setStats({
        libraryCount: libRes.data.total || 0,
        summaryCount: statsRes.data.summaryCount || 0,
      })
      if (prefRes?.data) setPreferences(prefRes.data)
      setChannelSubscriptions(subRes.data.items || [])
      setChannelUpdates(updatesRes.data.items || [])
      setChannelRequests(reqRes.data.items || [])
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (loading) return
    if (!hasPreference) {
      setShowPrefEditor(true)
    }
  }, [loading, hasPreference])

  const toggleValue = (key, val) => {
    setPreferences(prev => {
      const exists = prev[key].includes(val)
      return {
        ...prev,
        [key]: exists ? prev[key].filter(x => x !== val) : [...prev[key], val],
      }
    })
  }

  const addCustomArea = (value) => {
    const v = value.trim()
    if (!v) return
    setPreferences(prev => ({
      ...prev,
      researchAreas: prev.researchAreas.includes(v) ? prev.researchAreas : [...prev.researchAreas, v],
    }))
    setCustomArea('')
  }

  const savePreferences = async () => {
    try {
      const res = await api.put('/api/recommend/preferences', preferences)
      setPreferences(res.data)
      setShowPrefEditor(false)
      recentShownRef.current = []
      await loadRecommendations(true, [])
    } catch {
      // Keep interaction lightweight on dashboard; failures can be retried.
    }
  }

  const refreshCards = async () => {
    setRefreshing(true)
    const exclude = Array.from(new Set([
      ...recentShownRef.current,
      ...recommendations.map(item => item.articleNumber).filter(Boolean),
    ])).slice(-60)
    await loadRecommendations(true, exclude)
    setRefreshing(false)
  }

  const toggleChannelSubscription = (channelKey) => {
    setChannelSubscriptions(prev => prev.map(item => (
      item.key === channelKey ? { ...item, enabled: !item.enabled } : item
    )))
  }

  const saveChannelSubscriptions = async () => {
    setSavingChannels(true)
    try {
      const enabledChannelKeys = channelSubscriptions
        .filter(item => item.enabled)
        .map(item => item.key)
      const res = await api.put('/api/recommend/channels/subscriptions', { enabledChannelKeys })
      setChannelSubscriptions(res.data.items || [])
      const updatesRes = await api.get('/api/recommend/channels/updates', { params: { limit: 6, days: 30 } }).catch(() => ({ data: { items: [] } }))
      setChannelUpdates(updatesRes.data.items || [])
      alert('专栏订阅已保存')
    } catch (err) {
      alert(err.response?.data?.error || '保存订阅失败')
    } finally {
      setSavingChannels(false)
    }
  }

  const runChannelMonitorNow = async () => {
    setRunningChannelMonitor(true)
    try {
      const triggerRes = await api.post('/api/recommend/channels/monitor/trigger').catch(() => ({ data: { result: {} } }))
      const updatesRes = await api.get('/api/recommend/channels/updates', { params: { limit: 6, days: 30 } }).catch(() => ({ data: { items: [] } }))
      setChannelUpdates(updatesRes.data.items || [])
      await loadRecommendations(true)
      const added = triggerRes?.data?.result?.added ?? 0
      alert(`巡检完成，新增 ${added} 篇 Early Access 论文`)
    } catch (err) {
      alert(err.response?.data?.error || '巡检失败')
    } finally {
      setRunningChannelMonitor(false)
    }
  }

  const submitChannelRequest = async () => {
    if (requestTitle.trim().length < 2) {
      alert('请填写需求标题')
      return
    }
    setSubmittingRequest(true)
    try {
      await api.post('/api/recommend/channels/requests', {
        title: requestTitle,
        detail: requestDetail,
      })
      const reqRes = await api.get('/api/recommend/channels/requests/mine').catch(() => ({ data: { items: [] } }))
      setChannelRequests(reqRes.data.items || [])
      setRequestTitle('')
      setRequestDetail('')
      alert('需求已提交，48小时内会通过收件箱反馈审核结果')
    } catch (err) {
      alert(err.response?.data?.error || '需求提交失败')
    } finally {
      setSubmittingRequest(false)
    }
  }

  const requestStatusText = (status) => {
    if (status === 'approved') return '已采纳'
    if (status === 'rejected') return '未采纳'
    return '审核中'
  }

  if (loading) return <div className="page-loading">加载中...</div>

  return (
    <div className="dashboard">
      {/* Hero */}
      <div className="hero">
        <div className="hero-bg-pattern" />
        <div className="hero-content">
          <div className="hero-badge">arXiv · IEEE · Elsevier</div>
          <h1>PaperFlow</h1>
          <p className="hero-subtitle">智能学术论文推荐与个性化文献库管理平台</p>
          <div className="hero-actions">
            <Link to="/search" className="btn btn-accent">搜索论文</Link>
            <Link to="/recommendations" className="btn btn-ghost">查看推荐</Link>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon stat-icon-lib">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>
          </div>
          <div className="stat-number">{stats.libraryCount}</div>
          <div className="stat-label">我的论文库</div>
        </div>
        <div className="stat-card">
          <div className="stat-icon stat-icon-rec">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          </div>
          <div className="stat-number">{recommendations.length}</div>
          <div className="stat-label">个性化推荐</div>
        </div>
        <div className="stat-card">
          <div className="stat-icon stat-icon-ai">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
          </div>
          <div className="stat-number">{stats.summaryCount}</div>
          <div className="stat-label">AI 总结</div>
        </div>
        <div className="stat-card">
          <div className="stat-icon stat-icon-source">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>
          </div>
          <div className="stat-number">4</div>
          <div className="stat-label">数据源</div>
        </div>
      </div>

      {/* Paper recommendation cards */}
      <div className="dashboard-section">
        <div className="section-header">
          <h2>订阅推荐</h2>
          <div className="section-actions">
            <button className="btn btn-outline btn-sm" onClick={refreshCards} disabled={refreshing}>
              {refreshing ? '刷新中...' : '换一批'}
            </button>
            <button className="btn btn-outline btn-sm" onClick={() => setShowPrefEditor(v => !v)}>
              {showPrefEditor ? '收起偏好' : '编辑偏好'}
            </button>
            <Link to="/recommendations" className="btn btn-outline btn-sm">查看全部 →</Link>
          </div>
        </div>

        {!hasPreference && (
          <div className="pref-onboarding">
            <div>
              <strong>新账号建议先设置偏好</strong>
              <p>选择关注期刊和研究方向后，推荐结果会明显更准。</p>
            </div>
            <button className="btn btn-primary btn-sm" onClick={() => setShowPrefEditor(true)}>立即设置</button>
          </div>
        )}

        <div className="preference-summary">
          <span className="summary-label">期刊:</span>
          <span>{preferences.journals?.length ? preferences.journals.join(' / ') : '未设置'}</span>
          <span className="summary-label">方向:</span>
          <span>{preferences.researchAreas?.length ? preferences.researchAreas.join(' / ') : '未设置'}</span>
        </div>

        <div className="channel-subscription-panel">
          <div className="channel-subscription-header">
            <h3>专栏订阅提醒</h3>
            <div className="channel-subscription-actions">
              <button className="btn btn-outline btn-sm" onClick={runChannelMonitorNow} disabled={runningChannelMonitor}>
                {runningChannelMonitor ? '巡检中...' : '立即巡检'}
              </button>
              <button className="btn btn-outline btn-sm" onClick={saveChannelSubscriptions} disabled={savingChannels}>
                {savingChannels ? '保存中...' : '保存专栏订阅'}
              </button>
            </div>
          </div>
          {channelSubscriptions.length === 0 ? (
            <div className="empty-hint">暂无可订阅专栏</div>
          ) : (
            <div className="channel-subscription-list">
              {channelSubscriptions.map(item => (
                <label key={item.key} className={`channel-subscription-item ${item.enabled ? 'active' : ''}`}>
                  <input
                    type="checkbox"
                    checked={!!item.enabled}
                    onChange={() => toggleChannelSubscription(item.key)}
                  />
                  <div>
                    <div className="channel-subscription-title">{item.name}</div>
                    <div className="channel-subscription-desc">{item.description}</div>
                  </div>
                </label>
              ))}
            </div>
          )}

          {channelUpdates.length > 0 && (
            <div className="channel-update-section">
              <div className="pref-editor-label">近期 Early Access 更新卡片</div>
              <div className="channel-update-list">
                {channelUpdates.map(item => {
                  const paper = item.paper || {}
                  return (
                    <div
                      key={`${item.channelKey}-${item.articleNumber}`}
                      className="channel-update-card"
                      onClick={() => navigate(`/paper/${item.articleNumber}`)}
                    >
                      {paper.figurePath && (
                        <div className="channel-update-thumb">
                          <img src={`/api/figures/${paper.figurePath}`} alt="论文首图" loading="lazy" />
                        </div>
                      )}
                      <div className="channel-update-main">
                        <div className="channel-update-title">{paper.title || item.articleNumber}</div>
                        <div className="channel-update-meta">
                          <span>{item.channelName || 'IEEE Early Access'}</span>
                          {item.firstSeenAt && <span>{formatShanghaiDateTime(item.firstSeenAt)}</span>}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
          {channelUpdates.length === 0 && (
            <div className="empty-hint channel-update-empty">
              近期暂无 Early Access 新卡片，监控任务会持续轮询。
            </div>
          )}

          <div className="channel-request-box">
            <div className="pref-editor-label">没有你需要的期刊/专栏？提交需求（48小时内审核反馈）</div>
            <input
              value={requestTitle}
              onChange={e => setRequestTitle(e.target.value)}
              placeholder="例如：IEEE Transactions on Cybernetics 更新提醒"
            />
            <textarea
              value={requestDetail}
              onChange={e => setRequestDetail(e.target.value)}
              placeholder="描述你的专业方向、希望监控的期刊/专栏、更新频率等"
              rows={3}
            />
            <div className="channel-request-actions">
              <button className="btn btn-primary btn-sm" onClick={submitChannelRequest} disabled={submittingRequest}>
                {submittingRequest ? '提交中...' : '提交需求'}
              </button>
            </div>
            {channelRequests.length > 0 && (
              <div className="channel-request-history">
                <div className="pref-editor-label">我的需求进度</div>
                {channelRequests.slice(0, 5).map(item => (
                  <div key={item.id} className="channel-request-history-item">
                    <div>
                      <strong>{item.title}</strong>
                      <span className="channel-request-time">{formatShanghaiDateTime(item.createdAt)}</span>
                    </div>
                    <span className={`channel-request-status status-${item.status || 'pending'}`}>
                      {requestStatusText(item.status)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {showPrefEditor && (
          <div className="pref-editor">
            <div>
              <div className="pref-editor-label">期刊偏好</div>
              <div className="tag-options">
                {JOURNAL_OPTIONS.map(item => (
                  <button
                    key={item}
                    type="button"
                    className={`tag-option ${preferences.journals?.includes(item) ? 'active' : ''}`}
                    onClick={() => toggleValue('journals', item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="pref-editor-label">研究方向</div>
              <div className="tag-options">
                {AREA_OPTIONS.map(item => (
                  <button
                    key={item}
                    type="button"
                    className={`tag-option ${preferences.researchAreas?.includes(item) ? 'active' : ''}`}
                    onClick={() => toggleValue('researchAreas', item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
              <div className="custom-input-row">
                <input value={customArea} onChange={e => setCustomArea(e.target.value)} placeholder="添加自定义研究方向" />
                <button type="button" className="btn btn-outline btn-sm" onClick={() => addCustomArea(customArea)}>添加</button>
              </div>
            </div>
            <div className="pref-frequency-row">
              <button className="btn btn-primary btn-sm" onClick={savePreferences}>保存偏好</button>
            </div>
          </div>
        )}

        {recommendations.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--accent-light)" strokeWidth="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <p>暂无推荐论文</p>
            <p className="empty-hint">系统每天更新推荐，也可以手动换一批看看新内容。</p>
          </div>
        ) : (
          <div className="paper-grid">
            {recommendations.map(paper => (
              <div
                key={paper.articleNumber}
                className="mini-card"
                onClick={() => {
                  trackCardClick(paper.articleNumber, 'dashboard-card')
                  navigate(`/paper/${paper.articleNumber}`)
                }}
              >
                <div className="mini-card-source">
                  {(() => {
                    const src = getSourceInfo(paper)
                    return <span className={`source-badge ${src.cls}`}>{src.label}</span>
                  })()}
                  {paper.category && <span className="mini-card-category">{paper.category}</span>}
                  {paper.summary && <span className="ai-badge">AI ✓</span>}
                  {paper.avgRating != null && <span className="mini-card-rating">★ {paper.avgRating}</span>}
                </div>
                <h3 className="mini-card-title">{paper.title || '无标题'}</h3>
                {paper.keywords?.length > 0 && (
                  <div className="mini-card-keywords">
                    {paper.keywords.map((kw, i) => (
                      <span key={i} className="mini-keyword">{kw}</span>
                    ))}
                  </div>
                )}
                <p className="mini-card-authors">
                  {Array.isArray(paper.authors)
                    ? paper.authors.slice(0, 3).join(', ') + (paper.authors.length > 3 ? ' et al.' : '')
                    : paper.authors || ''}
                </p>
                <p className="mini-card-abstract">
                  {paper.abstract
                    ? paper.abstract.slice(0, 120) + '...'
                    : '暂无摘要'}
                </p>
                {paper.figurePath && (
                  <div className="mini-card-figure">
                    <img src={`/api/figures/${paper.figurePath}`} alt="论文插图" loading="lazy" />
                  </div>
                )}
                <div className="mini-card-footer">
                  <span className="mini-card-date">{paper.publicationDate || ''}</span>
                  <div className="mini-card-links">
                    {paper.sourceUrl && (
                      <a
                        href={paper.sourceUrl}
                        className="mini-source-link"
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={e => {
                          e.stopPropagation()
                          trackSourceClick(paper.articleNumber, 'dashboard-card')
                        }}
                      >
                        🔗 原文
                      </a>
                    )}
                    {paper.title && (
                      <a
                        href={`https://scholar.google.com/scholar?q=${encodeURIComponent(paper.title)}`}
                        className="mini-source-link"
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={e => e.stopPropagation()}
                      >
                        📚 搜索
                      </a>
                    )}
                    <span className="mini-card-action">查看详情 →</span>
                  </div>
                </div>
                <div onClick={e => e.stopPropagation()}>
                  <PaperComments articleNumber={paper.articleNumber} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Quick links */}
      <div className="quick-links">
        <Link to="/knowledge" className="quick-link-card">
          <svg className="quick-link-icon quick-link-icon-search" width="28" height="28" viewBox="0 0 24 24" fill="none" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <div>
            <h4>多源搜索</h4>
            <p>IEEE · arXiv · Elsevier</p>
          </div>
        </Link>
        <Link to="/library" className="quick-link-card">
          <svg className="quick-link-icon quick-link-icon-library" width="28" height="28" viewBox="0 0 24 24" fill="none" strokeWidth="2"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>
          <div>
            <h4>论文库</h4>
            <p>管理你收藏的 {stats.libraryCount} 篇论文</p>
          </div>
        </Link>
        <Link to="/recommendations" className="quick-link-card">
          <svg className="quick-link-icon quick-link-icon-recommendation" width="28" height="28" viewBox="0 0 24 24" fill="none" strokeWidth="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          <div>
            <h4>每日推荐</h4>
            <p>AI 精选顶会论文</p>
          </div>
        </Link>
      </div>
    </div>
  )
}
