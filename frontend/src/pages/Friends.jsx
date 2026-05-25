import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { formatShanghaiDateTime } from '../utils/time'
import './Friends.css'

export default function Friends() {
  const [tab, setTab] = useState('friends') // friends | search | requests | inbox | groups
  const [friends, setFriends] = useState([])
  const [requests, setRequests] = useState([])
  const [inbox, setInbox] = useState({ total: 0, items: [] })
  const [digests, setDigests] = useState({ total: 0, items: [] })
  const [searchQ, setSearchQ] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [loading, setLoading] = useState(false)

  // Group chat state
  const [groups, setGroups] = useState([])
  const [activeGroup, setActiveGroup] = useState(null)
  const [groupDetail, setGroupDetail] = useState(null)
  const [groupMessages, setGroupMessages] = useState([])
  const [msgInput, setMsgInput] = useState('')
  const [showCreateGroup, setShowCreateGroup] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [selectedMembers, setSelectedMembers] = useState([])
  const [showAddMember, setShowAddMember] = useState(false)
  const messagesEndRef = useRef(null)

  const loadFriends = useCallback(() => {
    api.get('/api/friends').then(r => setFriends(r.data)).catch(() => {})
  }, [])

  const loadRequests = useCallback(() => {
    api.get('/api/friends/requests').then(r => setRequests(r.data)).catch(() => {})
  }, [])

  const loadInbox = useCallback(() => {
    api.get('/api/friends/shares/inbox').then(r => setInbox(r.data)).catch(() => {})
  }, [])

  const loadDigests = useCallback(() => {
    api.get('/api/friends/digests/inbox').then(r => setDigests(r.data)).catch(() => {})
  }, [])

  const loadGroups = useCallback(() => {
    api.get('/api/groups').then(r => setGroups(r.data)).catch(() => {})
  }, [])

  const loadGroupMessages = useCallback((gid) => {
    api.get(`/api/groups/${gid}/messages`).then(r => {
      setGroupMessages(r.data.items)
      setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
    }).catch(() => {})
  }, [])

  const loadGroupDetail = useCallback((gid) => {
    api.get(`/api/groups/${gid}`).then(r => setGroupDetail(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    loadFriends()
    loadRequests()
    loadInbox()
    loadDigests()
    loadGroups()
  }, [loadFriends, loadRequests, loadInbox, loadDigests, loadGroups])

  const handleSearch = async () => {
    if (!searchQ.trim()) return
    setLoading(true)
    try {
      const r = await api.get('/api/friends/search', { params: { q: searchQ } })
      setSearchResults(r.data)
    } catch { /* empty */ }
    setLoading(false)
  }

  const sendRequest = async (friendId) => {
    try {
      await api.post('/api/friends/request', { friendId })
      handleSearch()
    } catch (e) {
      alert(e.response?.data?.error || '操作失败')
    }
  }

  const handleRequest = async (reqId, action) => {
    await api.put(`/api/friends/requests/${reqId}`, { action })
    loadRequests()
    loadFriends()
  }

  const removeFriend = async (fsId) => {
    if (!confirm('确认删除该好友？')) return
    await api.delete(`/api/friends/${fsId}`)
    loadFriends()
  }

  const markRead = async (shareId) => {
    await api.put(`/api/friends/shares/${shareId}/read`)
    loadInbox()
  }

  const markDigestRead = async (digestId) => {
    await api.put(`/api/friends/digests/${digestId}/read`)
    loadDigests()
  }

  const deleteShare = async (shareId) => {
    if (!confirm('确认删除这条消息？')) return
    await api.delete(`/api/friends/shares/${shareId}`)
    loadInbox()
  }

  const deleteDigest = async (digestId) => {
    if (!confirm('确认删除这条双周总结？')) return
    await api.delete(`/api/friends/digests/${digestId}`)
    loadDigests()
  }

  const openGroup = (group) => {
    setActiveGroup(group)
    loadGroupDetail(group.id)
    loadGroupMessages(group.id)
  }

  const closeGroup = () => {
    setActiveGroup(null)
    setGroupDetail(null)
    setGroupMessages([])
    setShowAddMember(false)
  }

  const createGroup = async () => {
    if (!newGroupName.trim()) return
    try {
      await api.post('/api/groups', { name: newGroupName, memberIds: selectedMembers })
      setShowCreateGroup(false)
      setNewGroupName('')
      setSelectedMembers([])
      loadGroups()
    } catch (e) {
      alert(e.response?.data?.error || '创建失败')
    }
  }

  const sendGroupMessage = async () => {
    if (!msgInput.trim() || !activeGroup) return
    try {
      await api.post(`/api/groups/${activeGroup.id}/messages`, { content: msgInput, messageType: 'text' })
      setMsgInput('')
      loadGroupMessages(activeGroup.id)
    } catch { /* empty */ }
  }

  const addMembersToGroup = async (memberIds) => {
    if (!activeGroup) return
    try {
      await api.post(`/api/groups/${activeGroup.id}/members`, { memberIds })
      loadGroupDetail(activeGroup.id)
      setShowAddMember(false)
    } catch { /* empty */ }
  }

  const leaveGroup = async (groupId) => {
    if (!confirm('确认退出该群聊？')) return
    try {
      const me = (await api.get('/api/auth/me')).data
      await api.delete(`/api/groups/${groupId}/members/${me.id}`)
      closeGroup()
      loadGroups()
    } catch (e) {
      alert(e.response?.data?.error || '操作失败')
    }
  }

  const deleteGroup = async (groupId) => {
    if (!confirm('确认解散该群聊？所有消息将被删除。')) return
    try {
      await api.delete(`/api/groups/${groupId}`)
      closeGroup()
      loadGroups()
    } catch (e) {
      alert(e.response?.data?.error || '操作失败')
    }
  }

  return (
    <div className="friends-page">
      <h2 className="friends-title">好友中心</h2>
      <div className="friends-tabs">
        <button className={tab === 'friends' ? 'active' : ''} onClick={() => setTab('friends')}>
          我的好友 ({friends.length})
        </button>
        <button className={tab === 'requests' ? 'active' : ''} onClick={() => setTab('requests')}>
          好友请求 {requests.length > 0 && <span className="tab-badge">{requests.length}</span>}
        </button>
        <button className={tab === 'inbox' ? 'active' : ''} onClick={() => setTab('inbox')}>
          消息收件箱 {(inbox.items.filter(s => !s.isRead).length + digests.items.filter(d => !d.isRead).length) > 0 && (
            <span className="tab-badge">{inbox.items.filter(s => !s.isRead).length + digests.items.filter(d => !d.isRead).length}</span>
          )}
        </button>
        <button className={tab === 'search' ? 'active' : ''} onClick={() => setTab('search')}>
          添加好友
        </button>
        <button className={tab === 'groups' ? 'active' : ''} onClick={() => { setTab('groups'); closeGroup() }}>
          群聊 ({groups.length})
        </button>
      </div>

      {/* My Friends */}
      {tab === 'friends' && (
        <div className="friends-list">
          {friends.length === 0 ? (
            <div className="friends-empty">还没有好友，去添加好友吧！</div>
          ) : friends.map(f => (
            <div key={f.id} className="friend-card">
              <div className="friend-avatar">{f.username[0].toUpperCase()}</div>
              <div className="friend-info">
                <span className="friend-name">{f.username}</span>
                <span className="friend-email">{f.email}</span>
              </div>
              <button className="btn btn-sm btn-danger" onClick={() => removeFriend(f.friendshipId)}>
                删除
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Friend Requests */}
      {tab === 'requests' && (
        <div className="friends-list">
          {requests.length === 0 ? (
            <div className="friends-empty">没有待处理的好友请求</div>
          ) : requests.map(r => (
            <div key={r.id} className="friend-card">
              <div className="friend-avatar">{r.requester.username[0].toUpperCase()}</div>
              <div className="friend-info">
                <span className="friend-name">{r.requester.username}</span>
                <span className="friend-email">请求添加您为好友</span>
              </div>
              <div className="friend-req-actions">
                <button className="btn btn-sm btn-primary" onClick={() => handleRequest(r.id, 'accept')}>
                  接受
                </button>
                <button className="btn btn-sm btn-outline" onClick={() => handleRequest(r.id, 'reject')}>
                  拒绝
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Inbox - received shares */}
      {tab === 'inbox' && (
        <div className="friends-list">
          {digests.items.length === 0 && inbox.items.length === 0 ? (
            <div className="friends-empty">暂无收到的消息</div>
          ) : (
            <>
              {digests.items.map(d => (
                <div key={`digest-${d.id}`} className={`share-card ${d.isRead ? '' : 'unread'}`}>
                  <div className="share-card-header">
                    <span className="share-from">
                      <strong>系统双周阅读回顾</strong>
                    </span>
                    <span className="share-time">{formatShanghaiDateTime(d.createdAt)}</span>
                  </div>
                  <div className="share-paper-info">
                    <span className="share-paper-title">{d.subject}</span>
                  </div>
                  {d.keywords?.length > 0 && (
                    <div className="share-message">关键词：{d.keywords.slice(0, 6).join(' / ')}</div>
                  )}
                  <div className="share-message" style={{ whiteSpace: 'pre-wrap' }}>{d.content}</div>
                  <div className="share-message">阅读 {d.readCount || 0} 篇 · 原文点击 {d.sourceClickCount || 0} 次</div>
                  {d.recommendedPapers?.length > 0 && (
                    <div className="digest-recommendations">
                      <div className="digest-recommendations-title">建议阅读</div>
                      <div className="digest-recommendation-list">
                        {d.recommendedPapers.map(paper => (
                          <Link key={paper.articleNumber} to={`/paper/${paper.articleNumber}`} className="digest-recommendation-card">
                            <div className="digest-recommendation-card-title">{paper.titleZh || paper.title}</div>
                            <div className="digest-recommendation-card-meta">
                              {paper.category || '未分类'}
                              {paper.publicationTitle ? ` · ${paper.publicationTitle}` : ''}
                            </div>
                          </Link>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="share-actions">
                    {!d.isRead && (
                      <button className="btn btn-sm btn-outline" onClick={() => markDigestRead(d.id)}>
                        标为已读
                      </button>
                    )}
                    <button className="btn btn-sm btn-danger" onClick={() => deleteDigest(d.id)}>
                      删除
                    </button>
                  </div>
                </div>
              ))}

              {inbox.items.map(s => (
                <div key={`share-${s.id}`} className={`share-card ${s.isRead ? '' : 'unread'}`}>
                  <div className="share-card-header">
                    <span className="share-from">
                      <strong>{s.fromUser.username}</strong> 推荐了一篇论文
                    </span>
                    <span className="share-time">{formatShanghaiDateTime(s.createdAt)}</span>
                  </div>
                  <div className="share-paper-info">
                    <Link to={`/paper/${s.paper.articleNumber}`} className="share-paper-title">
                      {s.paper.title}
                    </Link>
                    {s.paper.category && <span className="share-paper-cat">{s.paper.category}</span>}
                  </div>
                  {s.message && <div className="share-message">💬 {s.message}</div>}
                  <div className="share-actions">
                    {!s.isRead && (
                      <button className="btn btn-sm btn-outline" onClick={() => markRead(s.id)}>
                        标为已读
                      </button>
                    )}
                    <button className="btn btn-sm btn-danger" onClick={() => deleteShare(s.id)}>
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {/* Search Users */}
      {tab === 'search' && (
        <div className="friends-search">
          <div className="search-bar">
            <input
              type="text"
              placeholder="输入用户名搜索..."
              value={searchQ}
              onChange={e => setSearchQ(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
            />
            <button className="btn btn-primary" onClick={handleSearch} disabled={loading}>
              {loading ? '搜索中...' : '搜索'}
            </button>
          </div>
          <div className="friends-list">
            {searchResults.map(u => (
              <div key={u.id} className="friend-card">
                <div className="friend-avatar">{u.username[0].toUpperCase()}</div>
                <div className="friend-info">
                  <span className="friend-name">{u.username}</span>
                  <span className="friend-email">{u.email}</span>
                </div>
                {u.friendshipStatus === 'accepted' ? (
                  <span className="status-tag accepted">已是好友</span>
                ) : u.friendshipStatus === 'pending' ? (
                  <span className="status-tag pending">已发送请求</span>
                ) : (
                  <button className="btn btn-sm btn-primary" onClick={() => sendRequest(u.id)}>
                    加好友
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Groups */}
      {tab === 'groups' && !activeGroup && (
        <div className="groups-section">
          <div className="groups-header">
            <button className="btn btn-primary btn-sm" onClick={() => setShowCreateGroup(true)}>
              + 创建群聊
            </button>
          </div>
          {showCreateGroup && (
            <div className="create-group-form">
              <input
                type="text"
                placeholder="群聊名称"
                value={newGroupName}
                onChange={e => setNewGroupName(e.target.value)}
                maxLength={50}
              />
              <div className="create-group-members">
                <span className="create-group-label">选择成员：</span>
                {friends.length === 0 ? (
                  <span className="text-muted">暂无好友</span>
                ) : friends.map(f => (
                  <label key={f.id} className={`create-group-member ${selectedMembers.includes(f.id) ? 'selected' : ''}`}>
                    <input
                      type="checkbox"
                      checked={selectedMembers.includes(f.id)}
                      onChange={() => setSelectedMembers(prev =>
                        prev.includes(f.id) ? prev.filter(x => x !== f.id) : [...prev, f.id]
                      )}
                    />
                    {f.username}
                  </label>
                ))}
              </div>
              <div className="create-group-actions">
                <button className="btn btn-primary btn-sm" onClick={createGroup} disabled={!newGroupName.trim()}>
                  创建
                </button>
                <button className="btn btn-outline btn-sm" onClick={() => { setShowCreateGroup(false); setNewGroupName(''); setSelectedMembers([]) }}>
                  取消
                </button>
              </div>
            </div>
          )}
          <div className="friends-list">
            {groups.length === 0 ? (
              <div className="friends-empty">还没有群聊，创建一个吧！</div>
            ) : groups.map(g => (
              <div key={g.id} className="friend-card group-card" onClick={() => openGroup(g)}>
                <div className="friend-avatar group-avatar">群</div>
                <div className="friend-info">
                  <span className="friend-name">{g.name}</span>
                  <span className="friend-email">
                    {g.memberCount} 人
                    {g.lastMessage && (
                      <> · {g.lastMessage.username}: {g.lastMessage.content}</>
                    )}
                  </span>
                </div>
                <span className="group-arrow">›</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Group Chat View */}
      {tab === 'groups' && activeGroup && (
        <div className="group-chat-view">
          <div className="group-chat-header">
            <button className="btn btn-sm btn-outline" onClick={closeGroup}>← 返回</button>
            <h3>{activeGroup.name}</h3>
            <div className="group-chat-actions">
              <button className="btn btn-sm btn-outline" onClick={() => setShowAddMember(!showAddMember)}>
                + 邀请
              </button>
              {groupDetail && groupDetail.creatorId !== undefined && (
                <button className="btn btn-sm btn-danger" onClick={() =>
                  groupDetail.members?.find(m => m.role === 'creator')?.userId ===
                  groupDetail.members?.find(m => m.username)?.userId
                    ? deleteGroup(activeGroup.id)
                    : leaveGroup(activeGroup.id)
                }>
                  退出
                </button>
              )}
            </div>
          </div>

          {showAddMember && (
            <div className="add-member-panel">
              {friends.filter(f => !groupDetail?.members?.some(m => m.userId === f.id)).length === 0 ? (
                <div className="text-muted" style={{padding: '10px', fontSize: '13px'}}>所有好友都已在群中</div>
              ) : (
                friends.filter(f => !groupDetail?.members?.some(m => m.userId === f.id)).map(f => (
                  <div key={f.id} className="add-member-item">
                    <span>{f.username}</span>
                    <button className="btn btn-sm btn-primary" onClick={() => addMembersToGroup([f.id])}>
                      邀请
                    </button>
                  </div>
                ))
              )}
            </div>
          )}

          {groupDetail && (
            <div className="group-members-bar">
              {groupDetail.members?.map(m => (
                <span key={m.userId} className="group-member-chip" title={m.username}>
                  {m.username[0].toUpperCase()}
                </span>
              ))}
            </div>
          )}

          <div className="group-messages">
            {groupMessages.length === 0 ? (
              <div className="friends-empty">暂无消息，发送第一条消息吧！</div>
            ) : groupMessages.map(msg => (
              <div key={msg.id} className="group-msg">
                <div className="group-msg-header">
                  <span className="group-msg-user">{msg.username}</span>
                  <span className="group-msg-time">{formatShanghaiDateTime(msg.createdAt)}</span>
                </div>
                {msg.messageType === 'paper_share' && msg.paper ? (
                  <div className="group-msg-paper">
                    <Link to={`/paper/${msg.paper.articleNumber}`} className="group-msg-paper-title">
                      📄 {msg.paper.title}
                    </Link>
                    {msg.paper.category && <span className="share-paper-cat">{msg.paper.category}</span>}
                    {msg.content && <div className="group-msg-text">{msg.content}</div>}
                  </div>
                ) : (
                  <div className="group-msg-text">{msg.content}</div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <div className="group-input-bar">
            <input
              type="text"
              placeholder="输入消息..."
              value={msgInput}
              onChange={e => setMsgInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendGroupMessage()}
            />
            <button className="btn btn-primary btn-sm" onClick={sendGroupMessage} disabled={!msgInput.trim()}>
              发送
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
