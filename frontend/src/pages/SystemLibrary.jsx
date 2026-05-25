import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api'
import PaperCard from '../components/PaperCard'
import './SystemLibrary.css'

export default function SystemLibrary({ user }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [papers, setPapers] = useState([])
  const [categories, setCategories] = useState([])
  const [selectedCategory, setSelectedCategory] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [jumpPage, setJumpPage] = useState('1')
  const [total, setTotal] = useState(0)
  const [totalAll, setTotalAll] = useState(0)
  const [pages, setPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  const readPageFromQuery = () => {
    const raw = Number(searchParams.get('page') || 1)
    if (!Number.isFinite(raw) || raw < 1) return 1
    return Math.floor(raw)
  }

  const readCategoryFromQuery = () => (searchParams.get('category') || '').trim()
  const readKeywordFromQuery = () => (searchParams.get('keyword') || '').trim()

  const syncQuery = (p, cat, kw, replace = false) => {
    const next = new URLSearchParams()
    next.set('page', String(Math.max(1, Number(p) || 1)))
    if (cat) next.set('category', cat)
    if (kw) next.set('keyword', kw)
    setSearchParams(next, { replace })
  }

  const buildSystemLibraryReturnTo = (p = page, cat = selectedCategory, kw = keyword) => {
    const qs = new URLSearchParams()
    qs.set('page', String(Math.max(1, Number(p) || 1)))
    if (cat) qs.set('category', cat)
    if (kw) qs.set('keyword', kw)
    return `/system-library?${qs.toString()}`
  }

  const buildPageItems = (current, totalPages) => {
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

  const fetchCategories = async () => {
    try {
      const res = await api.get('/api/categories')
      const cats = res.data || []
      setCategories(cats)
      setTotalAll(cats.reduce((sum, c) => sum + c.count, 0))
    } catch {}
  }

  const fetchPapers = async (p = 1, cat = selectedCategory, kw = keyword, options = {}) => {
    const { sync = true, replace = false } = options
    setLoading(true)
    try {
      const params = { page: p, per_page: 20 }
      if (cat) params.category = cat
      if (kw) params.keyword = kw
      const res = await api.get('/api/system-library', { params })
      setPapers(res.data.items || [])
      setTotal(res.data.total || 0)
      const totalPages = Number(res.data.pages || 1)
      setPages(totalPages)
      setPage(p)
      setJumpPage(String(p))
      if (sync) syncQuery(p, cat, kw, replace)
    } catch {
      setPapers([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const initPage = readPageFromQuery()
    const initCategory = readCategoryFromQuery()
    const initKeyword = readKeywordFromQuery()
    setSelectedCategory(initCategory)
    setKeyword(initKeyword)
    setPage(initPage)
    setJumpPage(String(initPage))
    fetchCategories()
    fetchPapers(initPage, initCategory, initKeyword, { sync: true, replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleCategorySelect = (cat) => {
    setSelectedCategory(cat)
    fetchPapers(1, cat, keyword, { sync: true })
  }

  const handleSearch = (e) => {
    e.preventDefault()
    fetchPapers(1, selectedCategory, keyword, { sync: true })
  }

  const handleJump = (e) => {
    e.preventDefault()
    const target = Number(jumpPage)
    if (!Number.isFinite(target)) return
    const pageNum = Math.floor(target)
    if (pageNum < 1 || pageNum > pages) {
      alert(`请输入 1 到 ${pages} 之间的页码`)
      return
    }
    fetchPapers(pageNum, selectedCategory, keyword, { sync: true })
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
      alert('✅ 已添加到论文库！')
    } catch (err) {
      alert(err.response?.data?.error || '添加失败')
    }
  }

  const handleDeletePaper = async (paper) => {
    if (!user?.isAdmin) return
    const title = paper?.title || paper?.articleNumber || '该卡片'
    const ok = window.confirm(`确认删除卡片「${title}」？删除后不可恢复。`)
    if (!ok) return

    try {
      await api.delete(`/api/admin/papers/${paper.articleNumber}`)
      alert('🗑️ 卡片已删除')
      const nextTotal = Math.max(0, Number(total || 0) - 1)
      const nextPages = Math.max(1, Math.ceil(nextTotal / 20))
      const targetPage = Math.min(page, nextPages)
      await Promise.all([
        fetchCategories(),
        fetchPapers(targetPage, selectedCategory, keyword, { sync: true }),
      ])
    } catch (err) {
      alert(err.response?.data?.error || '删除失败')
    }
  }

  return (
    <div className="system-library">
      <div className="page-header">
        <h1>📚 系统论文库</h1>
        <div className="system-library-head-actions">
          <span className="library-total">共 {total} 篇论文</span>
        </div>
      </div>

      {/* Search bar */}
      <form className="sys-search-bar" onSubmit={handleSearch}>
        <input
          type="text"
          placeholder="搜索论文标题或摘要..."
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          className="sys-search-input"
        />
        <button type="submit" className="btn btn-primary">搜索</button>
      </form>

      <div className="sys-layout">
        {/* Category sidebar */}
        <aside className="category-sidebar">
          <h3>论文分类</h3>
          <div className="category-list">
            <button
              className={`category-item ${!selectedCategory ? 'active' : ''}`}
              onClick={() => handleCategorySelect('')}
            >
              <span className="cat-name">全部</span>
              <span className="cat-count">{totalAll}</span>
            </button>
            {categories.map(cat => (
              <button
                key={cat.name}
                className={`category-item ${selectedCategory === cat.name ? 'active' : ''}`}
                onClick={() => handleCategorySelect(cat.name)}
              >
                <span className="cat-name">{cat.name}</span>
                <span className="cat-count">{cat.count}</span>
              </button>
            ))}
          </div>
        </aside>

        {/* Paper list */}
        <div className="sys-paper-list">
          {loading ? (
            <div className="page-loading">加载中...</div>
          ) : papers.length === 0 ? (
            <div className="empty-state">
              <p>暂无论文</p>
              <p className="empty-hint">系统论文库会随着推荐和搜索自动充实</p>
            </div>
          ) : (
            <>
              {(() => {
                const detailState = {
                  source: 'system-library',
                  returnTo: buildSystemLibraryReturnTo(page, selectedCategory, keyword),
                  returnLabel: '返回系统论文库',
                }
                return papers.map(paper => (
                  <PaperCard
                    key={paper.articleNumber}
                    paper={paper}
                    detailState={detailState}
                    actions={
                      <div className="sys-card-actions">
                        <button
                          className="btn btn-sm btn-accent"
                          onClick={(e) => {
                            e.stopPropagation()
                            navigate(`/paper/${paper.articleNumber}`, { state: detailState })
                          }}
                        >
                          查看详情
                        </button>
                        <button
                          className="btn btn-sm btn-outline"
                          onClick={(e) => { e.stopPropagation(); handleAddToLibrary(paper) }}
                        >
                          加入论文库
                        </button>
                        {user?.isAdmin && (
                          <button
                            className="btn btn-sm btn-danger"
                            onClick={(e) => { e.stopPropagation(); handleDeletePaper(paper) }}
                          >
                            删除卡片
                          </button>
                        )}
                      </div>
                    }
                  />
                ))
              })()}
              {pages > 1 && (
                <div className="pagination">
                  <button
                    disabled={page <= 1}
                    onClick={() => fetchPapers(page - 1, selectedCategory, keyword, { sync: true })}
                    className="btn btn-sm btn-outline"
                  >
                    上一页
                  </button>
                  <div className="page-number-list">
                    {buildPageItems(page, pages).map((item, idx) => (
                      item === '...'
                        ? <span key={`dots-${idx}`} className="page-dots">…</span>
                        : (
                          <button
                            key={`page-${item}`}
                            className={`page-number-btn ${item === page ? 'active' : ''}`}
                            onClick={() => fetchPapers(item, selectedCategory, keyword, { sync: true })}
                          >
                            {item}
                          </button>
                        )
                    ))}
                  </div>
                  <span className="page-info">第 {page} / {pages} 页</span>
                  <button
                    disabled={page >= pages}
                    onClick={() => fetchPapers(page + 1, selectedCategory, keyword, { sync: true })}
                    className="btn btn-sm btn-outline"
                  >
                    下一页
                  </button>
                  <form className="page-jump-form" onSubmit={handleJump}>
                    <input
                      type="number"
                      min="1"
                      max={pages}
                      value={jumpPage}
                      onChange={(e) => setJumpPage(e.target.value)}
                      className="page-jump-input"
                    />
                    <button type="submit" className="btn btn-sm btn-outline">跳转</button>
                  </form>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
