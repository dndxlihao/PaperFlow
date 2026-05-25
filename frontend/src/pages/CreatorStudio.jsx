import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { formatShanghaiDateTime } from '../utils/time'
import './CreatorStudio.css'

const STATUS_TEXT = {
  pending: '待审核',
  approved: '已通过',
  rejected: '未通过',
  withdrawn: '已撤回',
}

const PROCESSING_TEXT = {
  pending: '排队中',
  processing: '生成中',
  ready: '已生成',
  failed: '生成失败',
}

export default function CreatorStudio() {
  const navigate = useNavigate()
  const [uploading, setUploading] = useState(false)
  const [loadingList, setLoadingList] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [items, setItems] = useState([])
  const [statusFilter, setStatusFilter] = useState('all')
  const [uploadPdfFile, setUploadPdfFile] = useState(null)
  const [uploadFileInputKey, setUploadFileInputKey] = useState(1)
  const [reviewActionLoadingId, setReviewActionLoadingId] = useState(null)
  const [editTarget, setEditTarget] = useState(null)
  const [editForm, setEditForm] = useState({
    publicationTitle: '',
    publicationDate: '',
    sourceUrl: '',
  })
  const [uploadForm, setUploadForm] = useState({
    title: '',
    authors: '',
    publicationTitle: '',
    publicationDate: '',
    sourceUrl: '',
    category: '',
    keywords: '',
    abstract: '',
  })

  const filteredItems = useMemo(() => {
    if (statusFilter === 'all') return items
    return items.filter(item => (item.creatorReviewStatus || 'approved') === statusFilter)
  }, [items, statusFilter])

  const fetchMyUploads = async () => {
    setLoadingList(true)
    try {
      const res = await api.get('/api/papers/my-uploads', { params: { page: 1, per_page: 60 } })
      setItems(res.data.items || [])
    } catch {
      setItems([])
    } finally {
      setLoadingList(false)
    }
  }

  useEffect(() => {
    fetchMyUploads()
  }, [])

  const resetUploadForm = () => {
    setUploadPdfFile(null)
    setUploadFileInputKey(prev => prev + 1)
    setUploadForm({
      title: '',
      authors: '',
      publicationTitle: '',
      publicationDate: '',
      sourceUrl: '',
      category: '',
      keywords: '',
      abstract: '',
    })
  }

  const updateUploadField = (key, value) => {
    setUploadForm(prev => ({ ...prev, [key]: value }))
  }

  const handleUploadCard = async (e) => {
    e.preventDefault()
    setError('')
    setMessage('')

    if (!uploadPdfFile) {
      setError('请先选择 PDF 文件')
      return
    }
    if (uploadPdfFile.size > 60 * 1024 * 1024) {
      setError('PDF 文件不能超过 60MB')
      return
    }
    if (!uploadForm.title.trim()) {
      setError('请填写论文标题')
      return
    }
    if (!uploadForm.authors.trim()) {
      setError('请至少填写一位作者')
      return
    }

    const formData = new FormData()
    formData.append('pdf', uploadPdfFile)
    formData.append('title', uploadForm.title.trim())
    formData.append('authors', uploadForm.authors.trim())
    if (uploadForm.publicationTitle.trim()) formData.append('publicationTitle', uploadForm.publicationTitle.trim())
    if (uploadForm.publicationDate.trim()) formData.append('publicationDate', uploadForm.publicationDate.trim())
    if (uploadForm.sourceUrl.trim()) formData.append('sourceUrl', uploadForm.sourceUrl.trim())
    if (uploadForm.category.trim()) formData.append('category', uploadForm.category.trim())
    if (uploadForm.keywords.trim()) formData.append('keywords', uploadForm.keywords.trim())
    if (uploadForm.abstract.trim()) formData.append('abstract', uploadForm.abstract.trim())
    formData.append('addToLibrary', '1')

    setUploading(true)
    try {
      const res = await api.post('/api/papers/upload-card', formData)
      const created = res.data?.paper
      setMessage(
        created?.articleNumber
          ? `投稿成功（${created.articleNumber}），系统正在生成内容并等待管理员审核。`
          : '投稿成功，系统正在生成内容并等待管理员审核。'
      )
      resetUploadForm()
      fetchMyUploads()
    } catch (err) {
      setError(err.response?.data?.error || '投稿失败，请稍后重试')
    } finally {
      setUploading(false)
    }
  }

  const handleOpenEditPublication = (item) => {
    setEditTarget(item)
    setEditForm({
      publicationTitle: item.publicationTitle || '',
      publicationDate: item.publicationDate || '',
      sourceUrl: item.sourceUrl || '',
    })
  }

  const handleSavePublication = async () => {
    if (!editTarget) return
    try {
      await api.patch(`/api/papers/${editTarget.articleNumber}/creator-publication`, {
        publicationTitle: editForm.publicationTitle,
        publicationDate: editForm.publicationDate,
        sourceUrl: editForm.sourceUrl,
      })
      setMessage('期刊信息已更新，并重新进入审核流程。')
      setEditTarget(null)
      fetchMyUploads()
    } catch (err) {
      setError(err.response?.data?.error || '更新失败')
    }
  }

  const handleResubmit = async (item) => {
    setReviewActionLoadingId(item.id)
    try {
      await api.post(`/api/papers/${item.articleNumber}/creator-resubmit`)
      setMessage('已重新提交审核。')
      fetchMyUploads()
    } catch (err) {
      setError(err.response?.data?.error || '提交失败')
    } finally {
      setReviewActionLoadingId(null)
    }
  }

  const handleWithdraw = async (item) => {
    const ok = window.confirm(`确认撤回投稿「${item.title || item.articleNumber}」吗？`)
    if (!ok) return
    setReviewActionLoadingId(item.id)
    try {
      await api.post(`/api/papers/${item.articleNumber}/creator-withdraw`)
      setMessage('投稿已撤回。')
      fetchMyUploads()
    } catch (err) {
      setError(err.response?.data?.error || '撤回失败')
    } finally {
      setReviewActionLoadingId(null)
    }
  }

  return (
    <div className="creator-studio">
      <section className="creator-hero">
        <div className="creator-hero-glow" />
        <div className="creator-hero-content">
          <span className="creator-kicker">Creator Studio</span>
          <h1>创作者中心</h1>
          <p>上传论文 PDF，自动抽取首图并生成 AI 总结；卡片经管理员审核后发布到系统论文库。</p>
        </div>
      </section>

      <section className="creator-panel">
        <div className="creator-panel-head">
          <h2>新建投稿</h2>
          <span>建议优先上传可复制文本的 PDF，以提升总结质量</span>
        </div>
        <form className="creator-form" onSubmit={handleUploadCard}>
          <div className="creator-form-grid">
            <input
              type="text"
              placeholder="论文标题（必填）"
              value={uploadForm.title}
              onChange={e => updateUploadField('title', e.target.value)}
              className="creator-input"
              required
            />
            <input
              type="text"
              placeholder="作者（必填，逗号分隔）"
              value={uploadForm.authors}
              onChange={e => updateUploadField('authors', e.target.value)}
              className="creator-input"
              required
            />
            <input
              type="text"
              placeholder="期刊/会议（可选）"
              value={uploadForm.publicationTitle}
              onChange={e => updateUploadField('publicationTitle', e.target.value)}
              className="creator-input"
            />
            <input
              type="text"
              placeholder="发表时间（可选，如 2026-05）"
              value={uploadForm.publicationDate}
              onChange={e => updateUploadField('publicationDate', e.target.value)}
              className="creator-input"
            />
            <input
              type="text"
              placeholder="研究方向（可选）"
              value={uploadForm.category}
              onChange={e => updateUploadField('category', e.target.value)}
              className="creator-input"
            />
            <input
              type="text"
              placeholder="关键词（可选，逗号分隔）"
              value={uploadForm.keywords}
              onChange={e => updateUploadField('keywords', e.target.value)}
              className="creator-input"
            />
          </div>
          <input
            type="text"
            placeholder="原文链接（可选）"
            value={uploadForm.sourceUrl}
            onChange={e => updateUploadField('sourceUrl', e.target.value)}
            className="creator-input creator-input-wide"
          />
          <textarea
            placeholder="摘要（可选）"
            value={uploadForm.abstract}
            onChange={e => updateUploadField('abstract', e.target.value)}
            className="creator-textarea"
            rows={4}
          />
          <div className="creator-form-actions">
            <input
              key={uploadFileInputKey}
              type="file"
              accept="application/pdf,.pdf"
              onChange={e => setUploadPdfFile(e.target.files?.[0] || null)}
              className="creator-file-input"
            />
            <button type="submit" className="btn btn-primary" disabled={uploading}>
              {uploading ? '投稿中...' : '提交投稿'}
            </button>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => navigate('/system-library')}
            >
              浏览系统论文库
            </button>
          </div>
          {error && <div className="creator-msg error">{error}</div>}
          {message && <div className="creator-msg success">{message}</div>}
        </form>
      </section>

      <section className="creator-panel">
        <div className="creator-panel-head">
          <h2>我的投稿</h2>
          <div className="creator-filters">
            {[
              ['all', '全部'],
              ['pending', '待审核'],
              ['approved', '已通过'],
              ['rejected', '未通过'],
              ['withdrawn', '已撤回'],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`creator-filter-btn ${statusFilter === key ? 'active' : ''}`}
                onClick={() => setStatusFilter(key)}
              >
                {label}
              </button>
            ))}
            <button type="button" className="creator-filter-btn" onClick={fetchMyUploads}>
              刷新
            </button>
          </div>
        </div>

        {loadingList ? (
          <div className="creator-empty">正在加载投稿记录...</div>
        ) : filteredItems.length === 0 ? (
          <div className="creator-empty">当前筛选下暂无投稿记录</div>
        ) : (
          <div className="creator-list">
            {filteredItems.map(item => {
              const reviewStatus = (item.creatorReviewStatus || 'approved').toLowerCase()
              const procStatus = (item.processingStatus || 'pending').toLowerCase()
              return (
                <article key={item.articleNumber} className="creator-item">
                  <div className="creator-item-main">
                    <h3>{item.title || item.articleNumber}</h3>
                    <div className="creator-meta">
                      <span className={`tag review-${reviewStatus}`}>{STATUS_TEXT[reviewStatus] || reviewStatus}</span>
                      <span className={`tag process-${procStatus}`}>{PROCESSING_TEXT[procStatus] || procStatus}</span>
                      <span className="tag neutral">{item.publicationTitle || '未填写期刊'}</span>
                      <span className="tag neutral">{formatShanghaiDateTime(item.createdAt) || '-'}</span>
                    </div>
                    {(item.creatorReviewNote || item.processingError) && (
                      <p className="creator-note">
                        {item.creatorReviewNote || item.processingError}
                      </p>
                    )}
                  </div>
                  <div className="creator-item-actions">
                    <button
                      type="button"
                      className="btn btn-outline btn-sm"
                      onClick={() => navigate(`/paper/${item.articleNumber}`, {
                        state: { source: 'creator-studio', returnTo: '/creator-studio', returnLabel: '返回创作者中心' },
                      })}
                    >
                      查看卡片
                    </button>
                    {reviewStatus === 'approved' && (
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => handleOpenEditPublication(item)}
                      >
                        修改期刊信息
                      </button>
                    )}
                    {reviewStatus === 'rejected' && (
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => handleResubmit(item)}
                        disabled={reviewActionLoadingId === item.id}
                      >
                        {reviewActionLoadingId === item.id ? '提交中...' : '重新提交审核'}
                      </button>
                    )}
                    {reviewStatus === 'pending' && (
                      <button
                        type="button"
                        className="btn btn-danger btn-sm"
                        onClick={() => handleWithdraw(item)}
                        disabled={reviewActionLoadingId === item.id}
                      >
                        {reviewActionLoadingId === item.id ? '处理中...' : '撤回投稿'}
                      </button>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>

      {editTarget && (
        <div className="creator-modal-mask" onClick={() => setEditTarget(null)}>
          <div className="creator-modal" onClick={e => e.stopPropagation()}>
            <h3>更新期刊信息</h3>
            <p>修改后会重新进入管理员审核，审核通过后再公开展示。</p>
            <input
              className="creator-input"
              placeholder="期刊/会议名称"
              value={editForm.publicationTitle}
              onChange={e => setEditForm(prev => ({ ...prev, publicationTitle: e.target.value }))}
            />
            <input
              className="creator-input"
              placeholder="发表时间（如 2026-08）"
              value={editForm.publicationDate}
              onChange={e => setEditForm(prev => ({ ...prev, publicationDate: e.target.value }))}
            />
            <input
              className="creator-input"
              placeholder="原文链接"
              value={editForm.sourceUrl}
              onChange={e => setEditForm(prev => ({ ...prev, sourceUrl: e.target.value }))}
            />
            <div className="creator-modal-actions">
              <button type="button" className="btn btn-outline" onClick={() => setEditTarget(null)}>
                取消
              </button>
              <button type="button" className="btn btn-primary" onClick={handleSavePublication}>
                保存并提交复审
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
