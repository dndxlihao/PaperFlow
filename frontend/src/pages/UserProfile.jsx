import { useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import api from '../api'
import PaperCard from '../components/PaperCard'
import { formatShanghaiDateTime } from '../utils/time'
import './UserProfile.css'

function readPageFromQuery(searchParams) {
  const raw = Number(searchParams.get('page') || 1)
  if (!Number.isFinite(raw) || raw < 1) return 1
  return Math.floor(raw)
}

function buildPageItems(current, totalPages) {
  if (totalPages <= 1) return [1]
  const items = [1]
  const start = Math.max(2, current - 2)
  const end = Math.min(totalPages - 1, current + 2)
  if (start > 2) items.push('...')
  for (let i = start; i <= end; i += 1) items.push(i)
  if (end < totalPages - 1) items.push('...')
  items.push(totalPages)
  return items
}

export default function UserProfile() {
  const { userId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [profile, setProfile] = useState(null)
  const [papers, setPapers] = useState([])
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [jumpPage, setJumpPage] = useState('1')

  const syncQuery = (p, replace = false) => {
    const next = new URLSearchParams()
    next.set('page', String(Math.max(1, Number(p) || 1)))
    setSearchParams(next, { replace })
  }

  const fetchProfile = async (targetPage = 1, { sync = true, replace = false } = {}) => {
    if (!userId) return
    setLoading(true)
    setError('')
    try {
      const res = await api.get(`/api/auth/users/${userId}/profile`, {
        params: { page: targetPage, per_page: 8 },
      })
      const nextProfile = res.data?.profile || null
      const paperPayload = res.data?.papers || {}
      const nextPages = Number(paperPayload.pages || 1)
      const nextPage = Number(paperPayload.page || targetPage || 1)
      setProfile(nextProfile)
      setPapers(paperPayload.items || [])
      setTotal(Number(paperPayload.total || 0))
      setPages(nextPages)
      setPage(nextPage)
      setJumpPage(String(nextPage))
      if (sync) syncQuery(nextPage, replace)
    } catch (err) {
      setError(err.response?.data?.error || '用户主页加载失败')
      setProfile(null)
      setPapers([])
      setTotal(0)
      setPages(1)
      setPage(1)
      setJumpPage('1')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const initPage = readPageFromQuery(searchParams)
    setPage(initPage)
    setJumpPage(String(initPage))
    fetchProfile(initPage, { sync: true, replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  const handleJump = (e) => {
    e.preventDefault()
    const target = Number(jumpPage)
    if (!Number.isFinite(target)) return
    const n = Math.floor(target)
    if (n < 1 || n > pages) {
      window.alert(`请输入 1 到 ${pages} 之间的页码`)
      return
    }
    fetchProfile(n, { sync: true })
  }

  const pageItems = useMemo(() => buildPageItems(page, pages), [page, pages])
  const detailState = useMemo(() => ({
    source: 'user-profile',
    returnTo: `/users/${encodeURIComponent(userId)}?page=${page}`,
    returnLabel: '返回个人主页',
  }), [page, userId])

  return (
    <div className="user-profile-page">
      {loading ? (
        <div className="page-loading">加载中...</div>
      ) : error ? (
        <div className="empty-state">
          <p>{error}</p>
        </div>
      ) : (
        <>
          <section className="user-profile-hero">
            <div className="user-profile-avatar">
              {profile?.avatarUrl ? (
                <img src={profile.avatarUrl} alt={profile.displayName || profile.username || '用户头像'} />
              ) : (
                <span>{(profile?.displayName || profile?.username || 'U')[0]?.toUpperCase() || 'U'}</span>
              )}
            </div>
            <div className="user-profile-main">
              <div className="user-profile-name-row">
                <h1>{profile?.displayName || profile?.username || '用户主页'}</h1>
                {profile?.username && <span className="user-profile-username">@{profile.username}</span>}
              </div>
              <div className="user-profile-meta">
                <span>加入时间：{formatShanghaiDateTime(profile?.createdAt) || '-'}</span>
                {profile?.isMe && <span className="user-profile-self-tag">这是你的主页</span>}
              </div>
              <p className="user-profile-bio">
                {profile?.bio || '这个用户还没有填写个人简介。'}
              </p>
              <div className="user-profile-areas">
                {(profile?.researchAreas || []).length > 0 ? (
                  (profile.researchAreas || []).map((area, idx) => (
                    <span key={`${area}-${idx}`} className="user-profile-area-tag">{area}</span>
                  ))
                ) : (
                  <span className="user-profile-areas-empty">暂未填写研究方向</span>
                )}
              </div>
            </div>
          </section>

          <section className="user-profile-papers">
            <div className="user-profile-papers-head">
              <h2>TA 创作的文章卡片</h2>
              <span>共 {total} 篇</span>
            </div>
            {papers.length === 0 ? (
              <div className="empty-state">
                <p>暂无可展示的创作卡片</p>
              </div>
            ) : (
              <>
                {papers.map(paper => (
                  <PaperCard
                    key={paper.articleNumber}
                    paper={paper}
                    detailState={detailState}
                  />
                ))}
                {pages > 1 && (
                  <div className="user-profile-pagination-wrap">
                    <div className="pagination">
                      <button
                        type="button"
                        className="btn btn-sm btn-outline"
                        disabled={page <= 1}
                        onClick={() => fetchProfile(page - 1, { sync: true })}
                      >
                        上一页
                      </button>
                      {pageItems.map((item, idx) => (
                        item === '...'
                          ? <span key={`ellipsis-${idx}`} className="page-ellipsis">...</span>
                          : (
                            <button
                              key={item}
                              type="button"
                              className={`page-number-btn ${item === page ? 'active' : ''}`}
                              onClick={() => fetchProfile(item, { sync: true })}
                            >
                              {item}
                            </button>
                          )
                      ))}
                      <button
                        type="button"
                        className="btn btn-sm btn-outline"
                        disabled={page >= pages}
                        onClick={() => fetchProfile(page + 1, { sync: true })}
                      >
                        下一页
                      </button>
                    </div>
                    <form className="user-profile-jump-form" onSubmit={handleJump}>
                      <span>跳到</span>
                      <input
                        type="number"
                        min="1"
                        max={pages}
                        value={jumpPage}
                        onChange={e => setJumpPage(e.target.value)}
                      />
                      <span>页</span>
                      <button type="submit" className="btn btn-sm btn-outline">前往</button>
                    </form>
                  </div>
                )}
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}
