import { useState, useEffect } from 'react'
import api from '../api'
import PaperCard from '../components/PaperCard'
import './PaperLibrary.css'

export default function PaperLibrary() {
  const [items, setItems] = useState([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(1)
  const [loading, setLoading] = useState(true)

  const fetchLibrary = async (p = 1) => {
    setLoading(true)
    try {
      const res = await api.get('/api/library', { params: { page: p, per_page: 20 } })
      setItems(res.data.items || [])
      setTotal(res.data.total || 0)
      setPages(res.data.pages || 1)
      setPage(p)
    } catch {
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchLibrary() }, [])

  const handleRemove = async (userPaperId) => {
    if (!confirm('确定要从论文库中移除？')) return
    try {
      await api.delete(`/api/library/${userPaperId}`)
      setItems(items.filter(i => i.userPaperId !== userPaperId))
      setTotal(t => t - 1)
    } catch (err) {
      alert('移除失败: ' + (err.response?.data?.error || err.message))
    }
  }

  const handleToggleFavorite = async (item) => {
    try {
      const res = await api.patch(`/api/library/${item.userPaperId}`, {
        isFavorite: !item.isFavorite,
      })
      setItems(items.map(i => i.userPaperId === item.userPaperId ? res.data : i))
    } catch {}
  }

  return (
    <div className="library-page">
      <div className="page-header">
        <h1>📚 我的论文库</h1>
        <span className="library-count">共 {total} 篇论文</span>
      </div>

      {loading ? (
        <div className="page-loading">加载中...</div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <p>论文库为空。前往「每日推荐」或「IEEE搜索」添加论文。</p>
        </div>
      ) : (
        <>
          {items.map(paper => (
            <PaperCard
              key={paper.userPaperId}
              paper={paper}
              actions={
                <>
                  <button
                    className={`btn btn-sm ${paper.isFavorite ? 'btn-warning' : 'btn-outline'}`}
                    onClick={() => handleToggleFavorite(paper)}
                  >
                    {paper.isFavorite ? '★ 已收藏' : '☆ 收藏'}
                  </button>
                  <button className="btn btn-sm btn-danger" onClick={() => handleRemove(paper.userPaperId)}>
                    移除
                  </button>
                </>
              }
            />
          ))}
          {pages > 1 && (
            <div className="pagination">
              <button disabled={page <= 1} onClick={() => fetchLibrary(page - 1)} className="btn btn-sm btn-outline">上一页</button>
              <span className="page-info">第 {page} / {pages} 页</span>
              <button disabled={page >= pages} onClick={() => fetchLibrary(page + 1)} className="btn btn-sm btn-outline">下一页</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
