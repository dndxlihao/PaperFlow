import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { formatShanghaiDateTime } from '../utils/time'
import './PaperComments.css'

function formatTime(iso) {
  return formatShanghaiDateTime(iso)
}

function countComments(items) {
  let total = 0
  for (const item of items || []) {
    total += 1 + countComments(item.replies || [])
  }
  return total
}

function updateCommentInTree(items, commentId, updater) {
  return (items || []).map(item => {
    if (item.id === commentId) {
      return updater(item)
    }
    if (item.replies?.length) {
      return {
        ...item,
        replies: updateCommentInTree(item.replies, commentId, updater),
      }
    }
    return item
  })
}

function getMentionContext(text, caretIndex) {
  if (typeof text !== 'string') return null
  const safeCaret = Number.isInteger(caretIndex) ? caretIndex : text.length
  if (safeCaret < 0 || safeCaret > text.length) return null

  const beforeCaret = text.slice(0, safeCaret)
  const match = beforeCaret.match(/(^|[\s([{])@([^\s@]{0,32})$/)
  if (!match) return null

  const query = match[2] || ''
  const start = beforeCaret.length - query.length - 1
  if (start < 0) return null
  return {
    query,
    start,
    end: safeCaret,
  }
}

function AuthorAvatar({ author }) {
  const displayName = author?.displayName || author?.username || 'U'
  if (author?.avatarUrl) {
    return <img className="paper-comment-avatar-img" src={author.avatarUrl} alt={displayName} />
  }
  return <span className="paper-comment-avatar-fallback">{displayName[0]?.toUpperCase() || 'U'}</span>
}

function CommentNode({ comment, depth, onLike, onReply, onEdit, onDelete, onOpenProfile }) {
  const indentClass = depth > 0 ? 'paper-comment-item nested' : 'paper-comment-item'
  const authorName = comment.author?.displayName || comment.author?.username || '匿名用户'
  return (
    <div className={indentClass}>
      <div className="paper-comment-avatar">
        <AuthorAvatar author={comment.author} />
      </div>
      <div className="paper-comment-main">
        <div className="paper-comment-head">
          {comment.author?.id ? (
            <button
              type="button"
              className="paper-comment-author link"
              onClick={() => onOpenProfile?.(comment.author)}
            >
              {authorName}
            </button>
          ) : (
            <span className="paper-comment-author">{authorName}</span>
          )}
          <span className="paper-comment-time">{formatTime(comment.createdAt)}</span>
        </div>
        <div className="paper-comment-content">{comment.content}</div>
        <div className="paper-comment-ops">
          <button
            type="button"
            className={`paper-comment-op ${comment.likedByMe ? 'active' : ''}`}
            onClick={() => onLike(comment.id)}
          >
            👍 {comment.likeCount || 0}
          </button>
          <button
            type="button"
            className="paper-comment-op"
            onClick={() => onReply(comment)}
          >
            回复
          </button>
          {comment.isMine && (
            <>
              <button
                type="button"
                className="paper-comment-op"
                onClick={() => onEdit(comment)}
              >
                编辑
              </button>
              <button
                type="button"
                className="paper-comment-op danger"
                onClick={() => onDelete(comment)}
              >
                删除
              </button>
            </>
          )}
        </div>
        {comment.replies?.length > 0 && (
          <div className="paper-comment-children">
            {comment.replies.map(child => (
              <CommentNode
                key={child.id}
                comment={child}
                depth={depth + 1}
                onLike={onLike}
                onReply={onReply}
                onEdit={onEdit}
                onDelete={onDelete}
                onOpenProfile={onOpenProfile}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function PaperComments({ articleNumber }) {
  const navigate = useNavigate()
  const textareaRef = useRef(null)
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [items, setItems] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [draft, setDraft] = useState('')
  const [replyTo, setReplyTo] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [totalCount, setTotalCount] = useState(0)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [mentionableFriends, setMentionableFriends] = useState([])
  const [mentionLoaded, setMentionLoaded] = useState(false)
  const [mentionLoading, setMentionLoading] = useState(false)
  const [mentionContext, setMentionContext] = useState(null)
  const [mentionActiveIndex, setMentionActiveIndex] = useState(0)

  const displayCount = useMemo(() => {
    if (loaded) return totalCount
    return countComments(items)
  }, [items, loaded, totalCount])

  const mentionCandidates = useMemo(() => {
    if (!mentionContext) return []
    const q = (mentionContext.query || '').trim().toLowerCase()
    const list = (mentionableFriends || []).filter(friend => {
      const username = (friend.username || '').toLowerCase()
      const displayName = (friend.displayName || '').toLowerCase()
      if (!q) return true
      return username.includes(q) || displayName.includes(q)
    })
    return list.slice(0, 8)
  }, [mentionContext, mentionableFriends])

  useEffect(() => {
    if (mentionActiveIndex >= mentionCandidates.length) {
      setMentionActiveIndex(0)
    }
  }, [mentionCandidates.length, mentionActiveIndex])

  const fetchComments = async ({ reset = false, targetPage = 1 } = {}) => {
    if (!articleNumber) return
    if (reset || targetPage <= 1) {
      setLoading(true)
    } else {
      setLoadingMore(true)
    }
    setError('')
    try {
      const res = await api.get(`/api/papers/${articleNumber}/comments`, {
        params: { page: targetPage, per_page: 8 },
      })
      const nextItems = res.data.items || []
      setItems(prev => {
        if (reset || targetPage <= 1) return nextItems
        return [...prev, ...nextItems]
      })
      setTotalCount(res.data.totalCount || 0)
      setPage(Number(res.data.page || targetPage || 1))
      setPages(Number(res.data.pages || 1))
      setHasMore(Boolean(res.data.hasMore))
      setLoaded(true)
    } catch (err) {
      setError(err.response?.data?.error || '评论加载失败')
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }

  const fetchMentionableFriends = async () => {
    if (mentionLoaded || mentionLoading) return
    setMentionLoading(true)
    try {
      const res = await api.get('/api/comments/mentionable-friends')
      setMentionableFriends(res.data.items || [])
      setMentionLoaded(true)
    } catch {
      // Keep this silent and rely on backend validation as the final gate.
    } finally {
      setMentionLoading(false)
    }
  }

  const toggleExpanded = async () => {
    const next = !expanded
    setExpanded(next)
    if (next) {
      fetchMentionableFriends()
      if (!loaded) {
        await fetchComments({ reset: true, targetPage: 1 })
      }
    } else {
      setMentionContext(null)
    }
  }

  const updateMentionStateFromInput = (value, caretIndex) => {
    const nextContext = getMentionContext(value, caretIndex)
    setMentionContext(nextContext)
    if (!nextContext) {
      setMentionActiveIndex(0)
    }
  }

  const handleDraftChange = (event) => {
    const nextValue = event.target.value
    setDraft(nextValue)
    updateMentionStateFromInput(nextValue, event.target.selectionStart)
  }

  const insertMention = (friend) => {
    if (!friend || !mentionContext) return
    const username = (friend.username || '').trim()
    const fallback = (friend.displayName || '').trim()
    const mentionName = username || fallback
    if (!mentionName) return

    const prefix = draft.slice(0, mentionContext.start)
    const suffix = draft.slice(mentionContext.end)
    const inserted = `@${mentionName} `
    const nextDraft = `${prefix}${inserted}${suffix}`
    const nextCursor = prefix.length + inserted.length

    setDraft(nextDraft)
    setMentionContext(null)
    setMentionActiveIndex(0)
    requestAnimationFrame(() => {
      if (!textareaRef.current) return
      textareaRef.current.focus()
      textareaRef.current.setSelectionRange(nextCursor, nextCursor)
    })
  }

  const handleDraftKeyDown = (event) => {
    if (!mentionContext || mentionCandidates.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setMentionActiveIndex(prev => (prev + 1) % mentionCandidates.length)
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setMentionActiveIndex(prev => (prev - 1 + mentionCandidates.length) % mentionCandidates.length)
      return
    }
    if ((event.key === 'Enter' || event.key === 'Tab') && !event.shiftKey) {
      event.preventDefault()
      insertMention(mentionCandidates[mentionActiveIndex] || mentionCandidates[0])
      return
    }
    if (event.key === 'Escape') {
      setMentionContext(null)
      setMentionActiveIndex(0)
    }
  }

  const submitComment = async () => {
    const content = draft.trim()
    if (!content || !articleNumber) return

    setSubmitting(true)
    setError('')
    try {
      await api.post(`/api/papers/${articleNumber}/comments`, {
        content,
        parentId: replyTo?.id ?? null,
      })
      setDraft('')
      setMentionContext(null)
      setMentionActiveIndex(0)
      setReplyTo(null)
      await fetchComments({ reset: true, targetPage: 1 })
    } catch (err) {
      setError(err.response?.data?.error || '评论发送失败')
    } finally {
      setSubmitting(false)
    }
  }

  const toggleLike = async (commentId) => {
    try {
      const res = await api.post(`/api/comments/${commentId}/like`)
      const likeCount = Number(res.data.likeCount || 0)
      const liked = !!res.data.liked
      setItems(prev => updateCommentInTree(prev, commentId, item => ({
        ...item,
        likeCount,
        likedByMe: liked,
      })))
    } catch {
      // Keep UI quiet for transient like failures.
    }
  }

  const editComment = async (comment) => {
    const next = window.prompt('编辑评论内容', comment.content || '')
    if (next == null) return
    const content = next.trim()
    if (!content) {
      window.alert('评论内容不能为空')
      return
    }
    if (content.length > 1500) {
      window.alert('评论内容不能超过1500字符')
      return
    }

    try {
      const res = await api.patch(`/api/comments/${comment.id}`, { content })
      const item = res.data?.item
      if (!item) return
      setItems(prev => updateCommentInTree(prev, comment.id, old => ({
        ...old,
        ...item,
        replies: old.replies || [],
      })))
    } catch (err) {
      window.alert(err.response?.data?.error || '编辑失败')
    }
  }

  const deleteComment = async (comment) => {
    if (!window.confirm('确认删除这条评论吗？')) return
    try {
      await api.delete(`/api/comments/${comment.id}`)
      await fetchComments({ reset: true, targetPage: 1 })
    } catch (err) {
      window.alert(err.response?.data?.error || '删除失败')
    }
  }

  const loadMore = async () => {
    if (loadingMore || !hasMore) return
    await fetchComments({ reset: false, targetPage: page + 1 })
  }

  const openAuthorProfile = (author) => {
    const uid = Number(author?.id)
    if (!Number.isFinite(uid) || uid <= 0) return
    navigate(`/users/${uid}`)
  }

  return (
    <div className="paper-comments">
      <button type="button" className="paper-comments-toggle" onClick={toggleExpanded}>
        {expanded ? '收起评论区' : '展开评论区'}{displayCount > 0 ? ` (${displayCount})` : ''}
      </button>

      {expanded && (
        <div className="paper-comments-panel">
          {error && <div className="paper-comments-error">{error}</div>}
          {loading ? (
            <div className="paper-comments-loading">评论加载中...</div>
          ) : (
            <>
              {(items || []).length === 0 ? (
                <div className="paper-comments-empty">暂无评论，来做第一个发言的人吧。</div>
              ) : (
                <div className="paper-comments-list">
                  {items.map(comment => (
                    <CommentNode
                      key={comment.id}
                      comment={comment}
                      depth={0}
                      onLike={toggleLike}
                      onReply={setReplyTo}
                      onEdit={editComment}
                      onDelete={deleteComment}
                      onOpenProfile={openAuthorProfile}
                    />
                  ))}
                </div>
              )}
              {!loading && (items || []).length > 0 && hasMore && (
                <div className="paper-comments-more">
                  <button
                    type="button"
                    className="btn btn-sm btn-outline"
                    disabled={loadingMore}
                    onClick={loadMore}
                  >
                    {loadingMore ? '加载中...' : `加载更多评论 (${page}/${pages})`}
                  </button>
                </div>
              )}
            </>
          )}

          <div className="paper-comments-editor">
            {replyTo && (
              <div className="paper-comments-reply-tip">
                正在回复：{replyTo.author?.displayName || replyTo.author?.username || '该用户'}
                <button type="button" onClick={() => setReplyTo(null)}>取消</button>
              </div>
            )}
            <div className="paper-comments-input-wrap">
              <textarea
                ref={textareaRef}
                value={draft}
                onChange={handleDraftChange}
                onClick={e => updateMentionStateFromInput(e.target.value, e.target.selectionStart)}
                onKeyUp={e => updateMentionStateFromInput(e.target.value, e.target.selectionStart)}
                onKeyDown={handleDraftKeyDown}
                placeholder={replyTo ? '写下你的回复（输入 @ 可选择好友）...' : '写下你的评论（输入 @ 可选择好友）...'}
                maxLength={1500}
              />
              {mentionContext && (
                <div className="paper-comments-mention-popover">
                  {mentionLoading && (
                    <div className="paper-comments-mention-row muted">好友列表加载中...</div>
                  )}
                  {!mentionLoading && mentionCandidates.length === 0 && (
                    <div className="paper-comments-mention-row muted">
                      {mentionableFriends.length === 0 ? '暂无可 @ 好友' : '未匹配到好友'}
                    </div>
                  )}
                  {!mentionLoading && mentionCandidates.map((friend, index) => (
                    <button
                      key={friend.id}
                      type="button"
                      className={`paper-comments-mention-row ${index === mentionActiveIndex ? 'active' : ''}`}
                      onMouseDown={event => {
                        event.preventDefault()
                        insertMention(friend)
                      }}
                    >
                      <span className="paper-comments-mention-name">{friend.displayName || friend.username}</span>
                      <span className="paper-comments-mention-username">@{friend.username || friend.displayName}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="paper-comments-editor-actions">
              <span>{draft.trim().length}/1500</span>
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={submitting || !draft.trim()}
                onClick={submitComment}
              >
                {submitting ? '发送中...' : (replyTo ? '回复' : '发表评论')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
