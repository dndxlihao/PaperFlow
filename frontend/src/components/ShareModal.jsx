import { useState, useEffect } from 'react'
import api from '../api'
import './ShareModal.css'

export default function ShareModal({ articleNumber, onClose }) {
  const [shareTab, setShareTab] = useState('friends') // friends | groups
  const [friends, setFriends] = useState([])
  const [groups, setGroups] = useState([])
  const [selected, setSelected] = useState([])
  const [selectedGroup, setSelectedGroup] = useState(null)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    api.get('/api/friends').then(r => setFriends(r.data)).catch(() => {})
    api.get('/api/groups').then(r => setGroups(r.data)).catch(() => {})
  }, [])

  const toggle = (id) => {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const handleSend = async () => {
    setSending(true)
    try {
      if (shareTab === 'friends') {
        if (selected.length === 0) return
        await api.post('/api/friends/share', {
          articleNumber,
          friendIds: selected,
          message,
        })
      } else {
        if (!selectedGroup) return
        await api.post(`/api/groups/${selectedGroup}/messages`, {
          articleNumber,
          messageType: 'paper_share',
          content: message,
        })
      }
      setDone(true)
      setTimeout(onClose, 1200)
    } catch {
      alert('分享失败')
    } finally {
      setSending(false)
    }
  }

  const canSend = shareTab === 'friends' ? selected.length > 0 : selectedGroup != null
  const sendLabel = shareTab === 'friends'
    ? `推荐给 ${selected.length} 位好友`
    : selectedGroup ? '分享到群聊' : '请选择群聊'

  return (
    <div className="share-modal-overlay" onClick={onClose}>
      <div className="share-modal" onClick={e => e.stopPropagation()}>
        <div className="share-modal-header">
          <h3>分享论文</h3>
          <button className="share-modal-close" onClick={onClose}>×</button>
        </div>
        {done ? (
          <div className="share-modal-done">✅ 已成功分享！</div>
        ) : (
          <>
            <div className="share-tabs">
              <button className={shareTab === 'friends' ? 'active' : ''} onClick={() => setShareTab('friends')}>
                👤 好友
              </button>
              <button className={shareTab === 'groups' ? 'active' : ''} onClick={() => setShareTab('groups')}>
                👥 群聊
              </button>
            </div>

            {shareTab === 'friends' && (
              friends.length === 0 ? (
                <div className="share-modal-empty">暂无好友，请先添加好友</div>
              ) : (
                <div className="share-modal-friends">
                  {friends.map(f => (
                    <label key={f.id} className={`share-friend-item ${selected.includes(f.id) ? 'selected' : ''}`}>
                      <input
                        type="checkbox"
                        checked={selected.includes(f.id)}
                        onChange={() => toggle(f.id)}
                      />
                      <span className="share-friend-avatar">{f.username[0].toUpperCase()}</span>
                      <span className="share-friend-name">{f.username}</span>
                    </label>
                  ))}
                </div>
              )
            )}

            {shareTab === 'groups' && (
              groups.length === 0 ? (
                <div className="share-modal-empty">暂无群聊，请先创建群聊</div>
              ) : (
                <div className="share-modal-friends">
                  {groups.map(g => (
                    <label key={g.id} className={`share-friend-item ${selectedGroup === g.id ? 'selected' : ''}`}>
                      <input
                        type="radio"
                        name="group"
                        checked={selectedGroup === g.id}
                        onChange={() => setSelectedGroup(g.id)}
                      />
                      <span className="share-friend-avatar share-group-avatar">群</span>
                      <span className="share-friend-name">{g.name}</span>
                      <span className="share-group-count">{g.memberCount}人</span>
                    </label>
                  ))}
                </div>
              )
            )}

            <textarea
              className="share-modal-msg"
              placeholder="附言（选填）"
              value={message}
              onChange={e => setMessage(e.target.value)}
              maxLength={500}
            />
            <button
              className="btn btn-primary share-modal-send"
              disabled={sending || !canSend}
              onClick={handleSend}
            >
              {sending ? '发送中...' : sendLabel}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
