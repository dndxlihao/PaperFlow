import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ShareModal from './ShareModal'
import PaperComments from './PaperComments'
import api from '../api'
import getSourceInfo from '../utils/sourceInfo'
import './PaperCard.css'

export default function PaperCard({ paper, actions, detailState = null }) {
  const [showShare, setShowShare] = useState(false)
  const navigate = useNavigate()
  const authorList = Array.isArray(paper.authors) ? paper.authors : (paper.authors || '').split(',').map(a => a.trim()).filter(Boolean)
  const source = getSourceInfo(paper)
  const keywords = paper.keywords || []
  const processingStatus = String(paper.processingStatus || 'ready').toLowerCase()
  const resolveFigureUrl = (figurePath) => {
    if (!figurePath) return ''
    if (/^https?:\/\//i.test(figurePath)) return figurePath
    return `/api/figures/${figurePath}`
  }

  const trackSourceClick = () => {
    if (!paper?.articleNumber) return
    api.post(`/api/papers/${paper.articleNumber}/source-click`, { context: 'paper-card' }).catch(() => {})
  }

  const trackCardClick = () => {
    if (!paper?.articleNumber) return
    api.post(`/api/papers/${paper.articleNumber}/card-click`, { context: 'paper-card-title' }).catch(() => {})
  }

  return (
    <div className="paper-card">
      <div className="paper-card-top">
        <span className={`source-badge ${source.cls}`}>{source.label}</span>
        {paper.isUserUploaded && <span className="card-origin-badge">用户创作</span>}
        {(processingStatus === 'pending' || processingStatus === 'processing') && (
          <span className="card-processing-badge status-processing">内容生成中</span>
        )}
        {processingStatus === 'failed' && (
          <span className="card-processing-badge status-failed" title={paper.processingError || ''}>生成失败</span>
        )}
        {paper.category && <span className="card-category-badge">{paper.category}</span>}
        {paper.summary && <span className="paper-summary-badge">AI 已总结</span>}
        <span className="card-rating">
          {paper.avgRating != null
            ? <>★ {paper.avgRating}<span className="card-rating-count"> ({paper.ratingCount || 0}人)</span></>
            : <span className="card-rating-none">暂无评分</span>}
        </span>
      </div>
      <div className="paper-card-header">
        <Link
          to={`/paper/${paper.articleNumber}`}
          state={detailState || undefined}
          className="paper-title"
          onClick={trackCardClick}
        >
          {paper.title || '无标题'}
        </Link>
      </div>
      {keywords.length > 0 && (
        <div className="paper-keywords">
          {keywords.map((kw, i) => (
            <span key={i} className="paper-keyword-tag">{kw}</span>
          ))}
        </div>
      )}
      <div className="paper-meta">
        {authorList.length > 0 && (
          <span className="paper-authors">👤{' '}
            {authorList.map((a, i) => (
              <span key={i}>
                <span
                  className="paper-author-link"
                  onClick={(e) => { e.stopPropagation(); navigate(`/scholars?author=${encodeURIComponent(a)}`) }}
                >{a}</span>
                {i < authorList.length - 1 && ', '}
              </span>
            ))}
          </span>
        )}
        {paper.publicationDate && <span className="paper-date">📅 {paper.publicationDate}</span>}
        {paper.downloadCount != null && paper.downloadCount > 0 && (
          <span className="paper-downloads">⬇ {paper.downloadCount}</span>
        )}
      </div>
      {paper.abstract && (
        <p className="paper-abstract">
          {paper.abstract.length > 260
            ? paper.abstract.slice(0, 260) + '...'
            : paper.abstract}
        </p>
      )}
      {paper.figurePath && (
        <div className="paper-figure-thumb">
          <img src={resolveFigureUrl(paper.figurePath)} alt="论文插图" loading="lazy" />
        </div>
      )}
      <div className="paper-actions">
        {paper.sourceUrl && (
          <a
            href={paper.sourceUrl}
            className="btn btn-sm btn-outline paper-source-link"
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => {
              e.stopPropagation()
              trackSourceClick()
            }}
          >
            🔗 跳转原文
          </a>
        )}
        {paper.title && (
          <a
            href={`https://scholar.google.com/scholar?q=${encodeURIComponent(paper.title)}`}
            className="btn btn-sm btn-outline paper-source-link"
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
          >
            📚 学术搜索
          </a>
        )}
        {actions}
        <Link
          to={`/paper/${paper.articleNumber}?edit=1`}
          state={detailState || undefined}
          className="btn btn-sm btn-outline paper-source-link"
          onClick={e => e.stopPropagation()}
        >
          ✏️ 申请纠错
        </Link>
        <button
          className="btn btn-sm btn-outline paper-share-btn"
          onClick={e => { e.stopPropagation(); setShowShare(true) }}
        >
          📤 分享
        </button>
      </div>
      {showShare && (
        <ShareModal
          articleNumber={paper.articleNumber}
          onClose={() => setShowShare(false)}
        />
      )}
      {paper?.articleNumber && (
        <PaperComments articleNumber={paper.articleNumber} />
      )}
    </div>
  )
}
