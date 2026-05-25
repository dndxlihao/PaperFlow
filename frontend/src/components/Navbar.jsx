import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import api from '../api'
import './Navbar.css'

const ABOUT_MENU_ITEMS = [
  { label: '项目背景', anchor: 'project-background' },
  { label: '运营团队', anchor: 'team' },
  { label: '版本更新', anchor: 'version-updates' },
]

export default function Navbar({ user, onLogout, onUserUpdate }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [badge, setBadge] = useState(0)
  const [adminReviewBadge, setAdminReviewBadge] = useState(0)
  const [showAccountPanel, setShowAccountPanel] = useState(false)
  const [showAboutMenu, setShowAboutMenu] = useState(false)
  const aboutMenuRef = useRef(null)
  const closeMenuTimerRef = useRef(null)
  const [profileForm, setProfileForm] = useState({
    username: '',
    displayName: '',
    bio: '',
    researchAreasText: '',
  })
  const [passwordForm, setPasswordForm] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' })
  const [avatarFile, setAvatarFile] = useState(null)

  useEffect(() => {
    if (!user) return
    setProfileForm({
      username: user.username || '',
      displayName: user.display_name || '',
      bio: user.profile_bio || '',
      researchAreasText: Array.isArray(user.profile_research_areas)
        ? user.profile_research_areas.join('，')
        : '',
    })
    setAvatarFile(null)
  }, [user])

  useEffect(() => {
    if (!user) return
    const fetchBadge = async () => {
      try {
        const friendRes = await api.get('/api/friends/shares/unread-count')
        setBadge(friendRes.data.totalUnread ?? ((friendRes.data.unreadShares || 0) + (friendRes.data.pendingRequests || 0)))
      } catch {
        // ignore
      }

      if (!user?.isAdmin) {
        setAdminReviewBadge(0)
        return
      }
      try {
        const reviewRes = await api.get('/api/admin/review-pending-count')
        setAdminReviewBadge(reviewRes.data.totalPendingReviews || 0)
      } catch {
        // ignore
      }
    }
    fetchBadge()
    const interval = setInterval(fetchBadge, 30000)
    return () => clearInterval(interval)
  }, [user])

  useEffect(() => {
    setShowAboutMenu(false)
  }, [location.pathname, location.hash])

  useEffect(() => {
    if (!showAboutMenu) return
    const handleClickOutside = (event) => {
      if (!aboutMenuRef.current?.contains(event.target)) {
        setShowAboutMenu(false)
      }
    }
    document.addEventListener('pointerdown', handleClickOutside)
    return () => {
      document.removeEventListener('pointerdown', handleClickOutside)
    }
  }, [showAboutMenu])

  useEffect(() => () => {
    if (closeMenuTimerRef.current) {
      clearTimeout(closeMenuTimerRef.current)
    }
  }, [])

  const handleLogout = () => {
    setShowAccountPanel(false)
    onLogout()
    navigate('/login')
  }

  const handleDeleteAccount = async () => {
    if (!confirm('确认注销当前账号？此操作会删除好友关系、收件箱、评分和群聊相关记录，且不可恢复。')) return
    try {
      await api.delete('/api/auth/me')
      onLogout()
      navigate('/register')
    } catch (err) {
      alert(err.response?.data?.error || '注销失败')
    }
  }

  const handleSaveProfile = async () => {
    try {
      const res = await api.patch('/api/auth/me', {
        username: profileForm.username,
        displayName: profileForm.displayName,
        bio: profileForm.bio,
        profileResearchAreas: profileForm.researchAreasText,
      })
      onUserUpdate?.(res.data)
      alert('个人信息已保存')
    } catch (err) {
      alert(err.response?.data?.error || '保存失败')
    }
  }

  const handleUploadAvatar = async () => {
    if (!avatarFile) {
      alert('请先选择头像文件')
      return
    }
    if (avatarFile.size > 5 * 1024 * 1024) {
      alert('头像文件不能超过 5MB')
      return
    }
    const formData = new FormData()
    formData.append('avatar', avatarFile)
    try {
      const res = await api.post('/api/auth/avatar', formData)
      onUserUpdate?.(res.data)
      setAvatarFile(null)
      alert('头像已更新')
    } catch (err) {
      const msg =
        err.response?.data?.error ||
        err.response?.data?.message ||
        err.message ||
        '头像上传失败'
      alert(msg)
    }
  }

  const handleChangePassword = async () => {
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      alert('两次输入的新密码不一致')
      return
    }
    try {
      await api.put('/api/auth/password', {
        currentPassword: passwordForm.currentPassword,
        newPassword: passwordForm.newPassword,
      })
      setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' })
      alert('密码修改成功')
    } catch (err) {
      alert(err.response?.data?.error || '修改密码失败')
    }
  }

  const isActive = (path) => location.pathname === path ? 'active' : ''
  const isAboutActive = location.pathname === '/about'

  const cancelCloseAboutMenu = () => {
    if (closeMenuTimerRef.current) {
      clearTimeout(closeMenuTimerRef.current)
      closeMenuTimerRef.current = null
    }
  }

  const scheduleCloseAboutMenu = () => {
    cancelCloseAboutMenu()
    closeMenuTimerRef.current = setTimeout(() => {
      setShowAboutMenu(false)
    }, 140)
  }

  const jumpToAbout = (anchor) => {
    cancelCloseAboutMenu()
    setShowAboutMenu(false)
    navigate(`/about#${anchor}`)
  }

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <Link to="/">
          <svg width="24" height="24" viewBox="0 0 32 32" style={{marginRight: 8, verticalAlign: 'middle'}}>
            <rect width="32" height="32" rx="6" fill="#1B4332"/>
            <text x="16" y="22" textAnchor="middle" fontFamily="Georgia,serif" fontSize="18" fontWeight="bold" fill="#D8F3DC">P</text>
            <line x1="8" y1="26" x2="24" y2="26" stroke="#95D5B2" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          PaperFlow
        </Link>
      </div>
      {user && (
        <div className="navbar-links">
          <Link to="/" className={isActive('/')}>首页</Link>
          <div
            ref={aboutMenuRef}
            className={`nav-dropdown ${isAboutActive ? 'active' : ''}`}
            onMouseEnter={() => {
              cancelCloseAboutMenu()
              setShowAboutMenu(true)
            }}
            onMouseLeave={(event) => {
              const nextTarget = event.relatedTarget
              if (nextTarget && aboutMenuRef.current?.contains(nextTarget)) return
              scheduleCloseAboutMenu()
            }}
            onFocus={() => {
              cancelCloseAboutMenu()
              setShowAboutMenu(true)
            }}
            onBlur={(event) => {
              const nextTarget = event.relatedTarget
              if (nextTarget && aboutMenuRef.current?.contains(nextTarget)) return
              setShowAboutMenu(false)
            }}
          >
            <button
              type="button"
              className={`nav-dropdown-trigger ${isAboutActive ? 'active' : ''}`}
              onClick={() => setShowAboutMenu(v => !v)}
              aria-expanded={showAboutMenu}
              aria-haspopup="menu"
            >
              关于我们
              <span className={`nav-caret ${showAboutMenu ? 'open' : ''}`}>▾</span>
            </button>
            <div className={`nav-dropdown-menu ${showAboutMenu ? 'open' : ''}`}>
              {ABOUT_MENU_ITEMS.map(item => (
                <button
                  key={item.anchor}
                  type="button"
                  className="nav-dropdown-item"
                  onClick={() => jumpToAbout(item.anchor)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <Link to="/recommendations" className={isActive('/recommendations')}>每日推荐</Link>
          <Link to="/knowledge" className={isActive('/knowledge')}>知识库</Link>
          <Link to="/scholars" className={isActive('/scholars')}>学术族谱</Link>
          <Link to="/system-library" className={isActive('/system-library')}>系统论文库</Link>
          <Link to="/creator-studio" className={isActive('/creator-studio')}>创作者中心</Link>
          <Link to="/library" className={isActive('/library')}>我的论文库</Link>
          <Link to="/friends" className={`${isActive('/friends')} navbar-friends-link`}>
            好友
            {badge > 0 && <span className="navbar-badge">{badge}</span>}
          </Link>
          {user?.isAdmin && (
            <Link to="/admin" className={`${isActive('/admin')} navbar-admin-link`}>
              管理后台
              {adminReviewBadge > 0 && <span className="navbar-badge">{adminReviewBadge}</span>}
            </Link>
          )}
        </div>
      )}
      <div className="navbar-right">
        {user ? (
          <>
            <button className="navbar-account-trigger" onClick={() => setShowAccountPanel(v => !v)}>
              <span className="navbar-account-avatar">
                {user.avatar_url ? <img src={user.avatar_url} alt={user.display_name || user.username} /> : (user.display_name || user.username)[0].toUpperCase()}
              </span>
              <span className="navbar-user">{user.display_name || user.username}</span>
            </button>
          </>
        ) : (
          <>
            <Link to="/login" className="btn btn-outline">登录</Link>
            <Link to="/register" className="btn btn-primary">注册</Link>
          </>
        )}
      </div>
      {user && showAccountPanel && (
        <div className="account-panel-overlay" onClick={() => setShowAccountPanel(false)}>
          <div className="account-panel" onClick={e => e.stopPropagation()}>
            <div className="account-panel-header">
              <div>
                <div className="account-panel-title">账号设置</div>
                <div className="account-panel-subtitle">管理头像、昵称、密码与账号操作</div>
              </div>
              <button className="account-panel-close" onClick={() => setShowAccountPanel(false)}>×</button>
            </div>

            <div className="account-panel-section">
              <label>头像</label>
              <div className="account-avatar-editor">
                <span className="account-avatar-preview">
                  {user.avatar_url ? <img src={user.avatar_url} alt={user.display_name || user.username} /> : (user.display_name || user.username)[0].toUpperCase()}
                </span>
                <div className="account-avatar-controls">
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/gif,image/webp"
                    onChange={e => setAvatarFile(e.target.files?.[0] || null)}
                  />
                  <button className="btn btn-outline" onClick={handleUploadAvatar}>上传本地头像</button>
                </div>
              </div>
              <label>账号名</label>
              <input
                type="text"
                placeholder="输入账号名（用于登录）"
                value={profileForm.username}
                onChange={e => setProfileForm(prev => ({ ...prev, username: e.target.value }))}
              />
              <label>昵称</label>
              <input
                type="text"
                placeholder="输入展示昵称"
                value={profileForm.displayName}
                onChange={e => setProfileForm(prev => ({ ...prev, displayName: e.target.value }))}
              />
              <label>个人简介</label>
              <textarea
                placeholder="可选：介绍你的研究兴趣与背景（最多2000字）"
                value={profileForm.bio}
                maxLength={2000}
                onChange={e => setProfileForm(prev => ({ ...prev, bio: e.target.value }))}
              />
              <label>研究方向</label>
              <input
                type="text"
                placeholder="可选：如 电力系统，强化学习，大语言模型（逗号分隔）"
                value={profileForm.researchAreasText}
                onChange={e => setProfileForm(prev => ({ ...prev, researchAreasText: e.target.value }))}
              />
              <button className="btn btn-primary" onClick={handleSaveProfile}>保存个人信息</button>
            </div>

            <div className="account-panel-section">
              <label>当前密码</label>
              <input
                type="password"
                value={passwordForm.currentPassword}
                onChange={e => setPasswordForm(prev => ({ ...prev, currentPassword: e.target.value }))}
              />
              <label>新密码</label>
              <input
                type="password"
                value={passwordForm.newPassword}
                onChange={e => setPasswordForm(prev => ({ ...prev, newPassword: e.target.value }))}
              />
              <label>确认新密码</label>
              <input
                type="password"
                value={passwordForm.confirmPassword}
                onChange={e => setPasswordForm(prev => ({ ...prev, confirmPassword: e.target.value }))}
              />
              <button className="btn btn-outline" onClick={handleChangePassword}>修改密码</button>
            </div>

            <div className="account-panel-section account-panel-actions">
              <button className="btn btn-outline" onClick={handleLogout}>退出登录</button>
              <button className="btn btn-danger" onClick={handleDeleteAccount}>注销账号</button>
            </div>
          </div>
        </div>
      )}
    </nav>
  )
}
