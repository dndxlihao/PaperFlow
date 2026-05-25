import { useEffect, useState } from 'react'
import api from '../api'
import { formatShanghaiDateTime } from '../utils/time'
import './AdminDashboard.css'

const WEIGHT_FIELDS = [
  { key: 'RECSCORE_FAVORITE_BONUS', label: '收藏加分' },
  { key: 'RECSCORE_RATING_FACTOR', label: '评分权重系数' },
  { key: 'RECSCORE_LIBRARY_PENALTY', label: '已在库惩罚' },
  { key: 'RECSCORE_DAILY_FRESHNESS_WEIGHT', label: 'Daily 新鲜度权重' },
  { key: 'RECSCORE_WEEKLY_FRESHNESS_WEIGHT', label: 'Weekly 新鲜度权重' },
  { key: 'RECSCORE_REALTIME_FRESHNESS_WEIGHT', label: 'Realtime 新鲜度权重' },
  { key: 'RECSCORE_DAILY_SHUFFLE_WEIGHT', label: 'Daily 随机扰动' },
  { key: 'RECSCORE_WEEKLY_SHUFFLE_WEIGHT', label: 'Weekly 随机扰动' },
  { key: 'RECSCORE_REALTIME_SHUFFLE_WEIGHT', label: 'Realtime 随机扰动' },
]

const STRATEGIES = ['daily', 'weekly', 'realtime', 'digest', 'channel_monitor', 'knowledge_index', 'knowledge_trends']

export default function AdminDashboard() {
  const [loading, setLoading] = useState(true)
  const [nowTs, setNowTs] = useState(Date.now())
  const [refreshingOps, setRefreshingOps] = useState(false)
  const [savingWeights, setSavingWeights] = useState(false)
  const [overview, setOverview] = useState(null)
  const [popular, setPopular] = useState([])
  const [jobStatus, setJobStatus] = useState({})
  const [weights, setWeights] = useState({})
  const [defaultWeights, setDefaultWeights] = useState({})
  const [preferences, setPreferences] = useState({
    libraryCategories: [],
    ratingCategories: [],
    activeUsers: [],
  })
  const [users, setUsers] = useState([])
  const [channelRequests, setChannelRequests] = useState([])
  const [paperEditRequests, setPaperEditRequests] = useState([])
  const [creatorSubmissions, setCreatorSubmissions] = useState([])
  const [reviewingRequestId, setReviewingRequestId] = useState(null)
  const [reviewingEditRequestId, setReviewingEditRequestId] = useState(null)
  const [reviewingCreatorSubmissionId, setReviewingCreatorSubmissionId] = useState(null)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [keyword, setKeyword] = useState('')

  const fetchAdminData = async (nextPage = page, nextKeyword = keyword) => {
    setLoading(true)
    try {
      const [overviewRes, popularRes, prefRes, usersRes, jobsRes, weightsRes, defaultsRes, channelReqRes, paperEditReqRes, creatorSubmissionRes] = await Promise.all([
        api.get('/api/admin/overview'),
        api.get('/api/admin/popular-papers', { params: { limit: 12 } }),
        api.get('/api/admin/preferences', { params: { limit: 8 } }),
        api.get('/api/admin/users', { params: { page: nextPage, per_page: 12, keyword: nextKeyword } }),
        api.get('/api/admin/recommend/jobs'),
        api.get('/api/admin/recommend/weights'),
        api.get('/api/admin/recommend/weights/defaults'),
        api.get('/api/admin/channel-requests', { params: { status: 'pending', per_page: 30 } }),
        api.get('/api/admin/paper-edit-requests', { params: { status: 'pending', per_page: 40 } }),
        api.get('/api/admin/creator-submissions', { params: { status: 'pending', per_page: 40 } }),
      ])

      setOverview(overviewRes.data)
      setPopular(popularRes.data.items || [])
      setPreferences(prefRes.data || { libraryCategories: [], ratingCategories: [], activeUsers: [] })
      setJobStatus(jobsRes.data || {})
      setWeights(weightsRes.data || {})
      setDefaultWeights(defaultsRes.data || {})
      setUsers(usersRes.data.items || [])
      setChannelRequests(channelReqRes.data.items || [])
      setPaperEditRequests(paperEditReqRes.data.items || [])
      setCreatorSubmissions(creatorSubmissionRes.data.items || [])
      setPage(usersRes.data.page || 1)
      setPages(usersRes.data.pages || 1)
    } catch (err) {
      alert(err.response?.data?.error || '管理员数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAdminData(1, '')
  }, [])

  const refreshOpsData = async (silent = false) => {
    if (!silent) setRefreshingOps(true)
    try {
      const [jobsRes, weightsRes] = await Promise.all([
        api.get('/api/admin/recommend/jobs'),
        api.get('/api/admin/recommend/weights'),
      ])
      setJobStatus(jobsRes.data || {})
      setWeights(weightsRes.data || {})
    } catch (err) {
      if (!silent) {
        alert(err.response?.data?.error || '推荐运维数据刷新失败')
      }
    } finally {
      if (!silent) setRefreshingOps(false)
    }
  }

  const handleWeightChange = (key, value) => {
    setWeights(prev => ({
      ...prev,
      [key]: value,
    }))
  }

  const handleSaveWeights = async () => {
    const payload = {}
    for (const item of WEIGHT_FIELDS) {
      const raw = weights[item.key]
      if (raw === '' || raw == null) continue
      const num = Number(raw)
      if (!Number.isFinite(num)) {
        alert(`${item.label} 不是有效数字`)
        return
      }
      payload[item.key] = num
    }

    setSavingWeights(true)
    try {
      const res = await api.patch('/api/admin/recommend/weights', payload)
      setWeights(res.data.weights || {})
      alert('权重更新成功，当前进程已生效')
    } catch (err) {
      alert(err.response?.data?.error || '权重更新失败')
    } finally {
      setSavingWeights(false)
    }
  }

  const handleRestoreDefaultWeights = async () => {
    let defaults = defaultWeights
    if (!defaults || Object.keys(defaults).length === 0) {
      try {
        const res = await api.get('/api/admin/recommend/weights/defaults')
        defaults = res.data || {}
        setDefaultWeights(defaults)
      } catch (err) {
        alert(err.response?.data?.error || '获取默认权重失败')
        return
      }
    }

    setWeights(defaults)
    alert('已回填后端默认权重，请点击“保存权重”使其在线生效')
  }

  const formatRelativeTime = (iso) => {
    if (!iso) return '-'
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso

    const diffSec = Math.floor((nowTs - d.getTime()) / 1000)
    if (diffSec < 0) return '刚刚'
    if (diffSec < 60) return `${diffSec} 秒前`

    const diffMin = Math.floor(diffSec / 60)
    if (diffMin < 60) return `${diffMin} 分钟前`

    const diffHour = Math.floor(diffMin / 60)
    if (diffHour < 24) return `${diffHour} 小时前`

    const diffDay = Math.floor(diffHour / 24)
    return `${diffDay} 天前`
  }

  useEffect(() => {
    const timer = setInterval(() => {
      setNowTs(Date.now())
      refreshOpsData(true)
    }, 30000)

    return () => clearInterval(timer)
  }, [])

  const handleSearch = (e) => {
    e.preventDefault()
    fetchAdminData(1, keyword)
  }

  const handleResetPassword = async (user) => {
    const pwd = window.prompt(`为用户 ${user.username} 设置新密码（至少6位）:`)
    if (!pwd) return
    try {
      await api.post(`/api/admin/users/${user.id}/reset-password`, { newPassword: pwd })
      alert('密码重置成功')
    } catch (err) {
      alert(err.response?.data?.error || '密码重置失败')
    }
  }

  const handleEditUser = async (user) => {
    const username = window.prompt('新用户名（留空则不修改）', user.username) || ''
    const email = window.prompt('新邮箱（留空则不修改）', user.email) || ''
    try {
      await api.patch(`/api/admin/users/${user.id}`, {
        username: username.trim(),
        email: email.trim(),
      })
      await fetchAdminData(page, keyword)
      alert('用户信息更新成功')
    } catch (err) {
      alert(err.response?.data?.error || '更新失败')
    }
  }

  const handleReviewChannelRequest = async (item, action) => {
    const note = window.prompt(
      action === 'approve' ? '填写采纳备注（可选）' : '填写拒绝原因（可选）',
      ''
    ) || ''
    setReviewingRequestId(item.id)
    try {
      await api.put(`/api/admin/channel-requests/${item.id}/review`, {
        action,
        note: note.trim(),
      })
      await fetchAdminData(page, keyword)
      alert(action === 'approve' ? '已采纳并通知用户' : '已拒绝并通知用户')
    } catch (err) {
      alert(err.response?.data?.error || '审核失败')
    } finally {
      setReviewingRequestId(null)
    }
  }

  const handleReviewPaperEditRequest = async (item, action) => {
    const note = window.prompt(
      action === 'approve' ? '填写通过备注（可选）' : '填写拒绝原因（可选）',
      ''
    ) || ''
    setReviewingEditRequestId(item.id)
    try {
      await api.put(`/api/admin/paper-edit-requests/${item.id}/review`, {
        action,
        note: note.trim(),
      })
      await fetchAdminData(page, keyword)
      alert(action === 'approve' ? '已通过并写回卡片内容' : '已拒绝该编辑申请')
    } catch (err) {
      alert(err.response?.data?.error || '审核失败')
    } finally {
      setReviewingEditRequestId(null)
    }
  }

  const handleReviewCreatorSubmission = async (item, action) => {
    const note = window.prompt(
      action === 'approve' ? '填写通过备注（可选）' : '填写驳回原因（可选）',
      ''
    ) || ''
    setReviewingCreatorSubmissionId(item.id)
    try {
      await api.put(`/api/admin/creator-submissions/${item.id}/review`, {
        action,
        note: note.trim(),
      })
      await fetchAdminData(page, keyword)
      alert(action === 'approve' ? '已通过创作者投稿' : '已驳回创作者投稿')
    } catch (err) {
      alert(err.response?.data?.error || '审核失败')
    } finally {
      setReviewingCreatorSubmissionId(null)
    }
  }

  if (loading) return <div className="page-loading">管理员后台加载中...</div>

  return (
    <div className="admin-page">
      <div className="admin-header">
        <h1>管理员后台</h1>
        <p>用户行为分析与账号管理</p>
      </div>

      {overview && (
        <div className="admin-kpis">
          <div className="kpi-card"><span>用户数</span><strong>{overview.users}</strong></div>
          <div className="kpi-card"><span>论文总量</span><strong>{overview.papers}</strong></div>
          <div className="kpi-card"><span>原文点击总量</span><strong>{overview.totalSourceClicks ?? overview.totalDownloads ?? 0}</strong></div>
          <div className="kpi-card"><span>评分数</span><strong>{overview.ratings}</strong></div>
          <div className="kpi-card"><span>收藏记录</span><strong>{overview.libraryItems}</strong></div>
          <div className="kpi-card"><span>推荐天数</span><strong>{overview.recommendationDays}</strong></div>
        </div>
      )}

      <div className="admin-grid">
        <section className="admin-panel">
          <h2>高点击卡片</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>论文</th>
                  <th>分类</th>
                  <th>原文点击</th>
                  <th>卡片点击</th>
                  <th>综合热度分</th>
                  <th>用户评分</th>
                </tr>
              </thead>
              <tbody>
                {popular.map(item => (
                  <tr key={item.articleNumber}>
                    <td>{item.titleZh || item.title || item.articleNumber}</td>
                    <td>{item.category || '-'}</td>
                    <td>{item.clickCount ?? 0}</td>
                    <td>{item.cardClickCount ?? 0}</td>
                    <td>{item.engagementScore ?? 0}</td>
                    <td>{item.avgRating != null ? `${item.avgRating} (${item.ratingCount})` : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="admin-panel">
          <h2>偏好分析（收藏分类）</h2>
          <ul className="simple-list">
            {preferences.libraryCategories.map(x => (
              <li key={x.name}><span>{x.name}</span><b>{x.count}</b></li>
            ))}
          </ul>
          <h2 className="sub-title">偏好分析（评分分类）</h2>
          <ul className="simple-list">
            {preferences.ratingCategories.map(x => (
              <li key={`r-${x.name}`}><span>{x.name}</span><b>{x.count}</b></li>
            ))}
          </ul>
        </section>
      </div>

      <div className="admin-grid admin-grid-ops">
        <section className="admin-panel">
          <div className="panel-head-row">
            <h2>推荐任务状态</h2>
            <button
              className="btn btn-outline btn-sm"
              onClick={refreshOpsData}
              disabled={refreshingOps}
            >
              {refreshingOps ? '刷新中...' : '刷新状态'}
            </button>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>策略</th>
                  <th>状态</th>
                  <th>开始时间</th>
                  <th>结束时间</th>
                  <th>耗时(ms)</th>
                  <th>消息</th>
                </tr>
              </thead>
              <tbody>
                {STRATEGIES.map((name) => {
                  const item = jobStatus[name] || {}
                  return (
                    <tr key={name}>
                      <td>{name}</td>
                      <td>
                        <span className={`job-state job-${item.lastStatus || 'never'}`}>
                          {item.lastStatus || 'never'}
                        </span>
                      </td>
                      <td>{formatRelativeTime(item.lastStartedAt)}</td>
                      <td>{formatRelativeTime(item.lastFinishedAt)}</td>
                      <td>{item.lastDurationMs ?? '-'}</td>
                      <td className="message-cell">{item.lastMessage || '-'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="admin-panel">
          <div className="panel-head-row">
            <h2>推荐权重调参</h2>
            <div className="ops-actions">
              <button
                className="btn btn-outline btn-sm"
                onClick={handleRestoreDefaultWeights}
                disabled={savingWeights}
              >
                恢复默认权重
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleSaveWeights}
                disabled={savingWeights}
              >
                {savingWeights ? '保存中...' : '保存权重'}
              </button>
            </div>
          </div>
          <p className="ops-note">修改后即时生效于当前进程，重启后会回到配置/环境变量值。</p>
          <div className="weight-grid">
            {WEIGHT_FIELDS.map((item) => (
              <label className="weight-item" key={item.key}>
                <span>{item.label}</span>
                <input
                  type="number"
                  step="0.01"
                  value={weights[item.key] ?? ''}
                  onChange={(e) => handleWeightChange(item.key, e.target.value)}
                />
              </label>
            ))}
          </div>
        </section>
      </div>

      <section className="admin-panel">
        <div className="panel-head-row">
          <h2>创作者投稿审核（待处理）</h2>
          <span className="ops-note">投稿卡片仅在审核通过后进入系统论文库</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>论文</th>
                <th>投稿人</th>
                <th>期刊信息</th>
                <th>生成状态</th>
                <th>提交时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {creatorSubmissions.length === 0 ? (
                <tr>
                  <td colSpan="6">暂无待审核创作者投稿</td>
                </tr>
              ) : (
                creatorSubmissions.map(item => (
                  <tr key={item.id}>
                    <td>
                      <a href={`/paper/${item.articleNumber}`} target="_blank" rel="noreferrer">
                        {item.title || item.articleNumber}
                      </a>
                    </td>
                    <td>{item.creatorDisplayName || item.creatorUsername || '-'}</td>
                    <td>{item.publicationTitle || '-'}</td>
                    <td>{item.processingStatus || '-'}</td>
                    <td>{formatShanghaiDateTime(item.createdAt) || '-'}</td>
                    <td>
                      <button
                        className="btn btn-sm btn-primary"
                        disabled={reviewingCreatorSubmissionId === item.id}
                        onClick={() => handleReviewCreatorSubmission(item, 'approve')}
                      >
                        通过
                      </button>
                      <button
                        className="btn btn-sm btn-outline"
                        disabled={reviewingCreatorSubmissionId === item.id}
                        onClick={() => handleReviewCreatorSubmission(item, 'reject')}
                      >
                        驳回
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="admin-panel">
        <div className="panel-head-row">
          <h2>卡片编辑审核（待处理）</h2>
          <span className="ops-note">用户可提交 AI 总结/图片解读修订，审核通过后自动写回卡片</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>论文</th>
                <th>申请人</th>
                <th>类型</th>
                <th>理由</th>
                <th>提交时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {paperEditRequests.length === 0 ? (
                <tr>
                  <td colSpan="6">暂无待审核编辑申请</td>
                </tr>
              ) : (
                paperEditRequests.map(item => (
                  <tr key={item.id}>
                    <td>
                      <a href={`/paper/${item.articleNumber}`} target="_blank" rel="noreferrer">
                        {item.paperTitle || item.articleNumber}
                      </a>
                    </td>
                    <td>{item.displayName || item.username || '-'}</td>
                    <td>{item.requestType || '-'}</td>
                    <td>
                      <div>{item.reason || '-'}</div>
                      {item?.changes?.figurePath?.to && (
                        <a
                          href={
                            /^https?:\/\//i.test(item.changes.figurePath.to)
                              ? item.changes.figurePath.to
                              : `/api/figures/${item.changes.figurePath.to}`
                          }
                          target="_blank"
                          rel="noreferrer"
                        >
                          查看修订图片
                        </a>
                      )}
                    </td>
                    <td>{formatShanghaiDateTime(item.createdAt) || '-'}</td>
                    <td>
                      <button
                        className="btn btn-sm btn-primary"
                        disabled={reviewingEditRequestId === item.id}
                        onClick={() => handleReviewPaperEditRequest(item, 'approve')}
                      >
                        通过
                      </button>
                      <button
                        className="btn btn-sm btn-outline"
                        disabled={reviewingEditRequestId === item.id}
                        onClick={() => handleReviewPaperEditRequest(item, 'reject')}
                      >
                        拒绝
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="admin-panel">
        <div className="panel-head-row">
          <h2>专栏需求审核（待处理）</h2>
          <span className="ops-note">用户提交后系统已自动告知 48 小时内反馈</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>需求标题</th>
                <th>需求说明</th>
                <th>提交时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {channelRequests.length === 0 ? (
                <tr>
                  <td colSpan="5">暂无待审核需求</td>
                </tr>
              ) : (
                channelRequests.map(item => (
                  <tr key={item.id}>
                    <td>{item.username || '-'}</td>
                    <td>{item.title}</td>
                    <td>{item.detail || '-'}</td>
                    <td>{formatShanghaiDateTime(item.createdAt) || '-'}</td>
                    <td>
                      <button
                        className="btn btn-sm btn-primary"
                        disabled={reviewingRequestId === item.id}
                        onClick={() => handleReviewChannelRequest(item, 'approve')}
                      >
                        采纳
                      </button>
                      <button
                        className="btn btn-sm btn-outline"
                        disabled={reviewingRequestId === item.id}
                        onClick={() => handleReviewChannelRequest(item, 'reject')}
                      >
                        拒绝
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="admin-panel">
        <div className="panel-head-row">
          <h2>账号管理</h2>
          <form onSubmit={handleSearch} className="search-box">
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索用户名/邮箱"
            />
            <button type="submit" className="btn btn-primary">查询</button>
          </form>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>邮箱</th>
                <th>收藏</th>
                <th>评分</th>
                <th>分享</th>
                <th>角色</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td>{u.username}</td>
                  <td>{u.email}</td>
                  <td>{u.libraryCount}</td>
                  <td>{u.ratingCount}</td>
                  <td>{u.shareCount}</td>
                  <td>{u.isAdmin ? '管理员' : '普通用户'}</td>
                  <td>
                    <button className="btn btn-sm btn-outline" onClick={() => handleEditUser(u)}>编辑</button>
                    <button className="btn btn-sm btn-primary" onClick={() => handleResetPassword(u)}>重置密码</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="pager">
          <button className="btn btn-outline" disabled={page <= 1} onClick={() => fetchAdminData(page - 1, keyword)}>上一页</button>
          <span>{page} / {pages}</span>
          <button className="btn btn-outline" disabled={page >= pages} onClick={() => fetchAdminData(page + 1, keyword)}>下一页</button>
        </div>
      </section>
    </div>
  )
}
