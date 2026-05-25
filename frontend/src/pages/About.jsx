import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import api from '../api'
import './About.css'

const ABOUT_EDITOR_USERNAME = 'Manager1'

const DEFAULT_CONTENT = {
  hero: {
    badge: 'About PaperFlow',
    title: '关于我们',
    subtitle: '面向跨学科科研与技术创新场景，构建检索、阅读、推荐、互动一体化的开放学术协同平台。',
  },
  projectBackground: [
    'PaperFlow 起步于电力与能源交叉方向的文献痛点：论文数量增长快、跨源检索分散、阅读沉淀难复用。平台将 IEEE、arXiv、Elsevier 等来源聚合到统一入口，并结合 AI 摘要与偏好推荐，帮助用户缩短从“发现文献”到“形成研究判断”的路径。',
    '随着自动化科研范式逐步成为主流，我们希望提供一个自由、开放、可持续沉淀的学术交流窗口。用户能够围绕论文进行评论、回复、评分与分享，让研究想法更快被讨论、被验证、被延展。',
    '在科研传播层面，平台同样有助于稿件推广和同行快速审阅：研究者可以更高效地触达目标读者，同行可以在结构化信息与互动反馈中快速理解论文价值，从而形成更高质量的学术协作闭环。',
  ],
  lead: {
    name: '总负责人（待完善）',
    avatarUrl: '',
    role: '总体统筹、产品方向与学术协同',
    experience: '负责平台战略规划、跨团队协作与关键项目推进，持续优化学术产品体验与社区生态建设。',
  },
  teams: [
    {
      id: 'team-product',
      title: '产品与学术运营组',
      description: '负责产品路线、学术需求调研与专题栏目规划。',
      members: [],
    },
    {
      id: 'team-algo',
      title: '推荐算法组',
      description: '负责个性化推荐策略、评分权重与反馈闭环优化。',
      members: [],
    },
    {
      id: 'team-engineering',
      title: '平台工程组',
      description: '负责数据抓取、服务稳定性、性能与安全保障。',
      members: [],
    },
  ],
  versionUpdates: [
    { version: 'v1.3', date: '2026-05', updates: '新增论文评论区、回复与点赞；支持互动消息提醒。' },
    { version: 'v1.2', date: '2026-04', updates: '上线双周阅读简报、专栏订阅提醒、管理员推荐权重调节。' },
    { version: 'v1.1', date: '2026-03', updates: '个性化推荐增强，支持研究方向偏好与实时刷新策略。' },
    { version: 'v1.0', date: '2026-02', updates: '完成论文搜索、AI 总结、论文库和基础社交分享功能。' },
  ],
}

function normalizeContent(raw) {
  const content = { ...DEFAULT_CONTENT, ...(raw || {}) }
  content.hero = { ...DEFAULT_CONTENT.hero, ...(raw?.hero || {}) }
  content.projectBackground = Array.isArray(raw?.projectBackground) && raw.projectBackground.length
    ? raw.projectBackground
    : DEFAULT_CONTENT.projectBackground
  content.lead = { ...DEFAULT_CONTENT.lead, ...(raw?.lead || {}) }
  content.teams = Array.isArray(raw?.teams) && raw.teams.length ? raw.teams : DEFAULT_CONTENT.teams
  content.versionUpdates = Array.isArray(raw?.versionUpdates) && raw.versionUpdates.length
    ? raw.versionUpdates
    : DEFAULT_CONTENT.versionUpdates
  return content
}

export default function About({ user }) {
  const location = useLocation()
  const [content, setContent] = useState(DEFAULT_CONTENT)
  const [draft, setDraft] = useState(DEFAULT_CONTENT)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [canEdit, setCanEdit] = useState(false)
  const [expandedTeams, setExpandedTeams] = useState({})
  const [meta, setMeta] = useState({ updatedBy: '', updatedAt: '' })

  const matchesAboutEditor = (profile) => {
    const target = ABOUT_EDITOR_USERNAME.toLowerCase()
    const username = (profile?.username || '').trim().toLowerCase()
    const displayName = (profile?.display_name || '').trim().toLowerCase()
    return username === target || displayName === target
  }

  const loadContent = async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/about/content')
      const next = normalizeContent(res.data?.content)
      setContent(next)
      setDraft(next)
      setCanEdit(Boolean(res.data?.canEdit))
      setMeta({
        updatedBy: res.data?.updatedBy || '',
        updatedAt: res.data?.updatedAt || '',
      })
      const defaultExpanded = {}
      for (const team of next.teams || []) defaultExpanded[team.id] = false
      setExpandedTeams(defaultExpanded)
    } catch {
      const fallback = normalizeContent(DEFAULT_CONTENT)
      setContent(fallback)
      setDraft(fallback)
      setCanEdit(Boolean(user?.isAdmin && matchesAboutEditor(user)))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadContent()
  }, [])

  useEffect(() => {
    if (!location.hash) return
    const id = location.hash.replace('#', '')
    const node = document.getElementById(id)
    if (node) {
      node.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [location.hash])

  const toggleTeam = (teamId) => {
    setExpandedTeams(prev => ({ ...prev, [teamId]: !prev[teamId] }))
  }

  const updateDraftHero = (field, value) => {
    setDraft(prev => ({ ...prev, hero: { ...prev.hero, [field]: value } }))
  }

  const updateBackgroundParagraph = (index, value) => {
    setDraft(prev => {
      const next = [...prev.projectBackground]
      next[index] = value
      return { ...prev, projectBackground: next }
    })
  }

  const addBackgroundParagraph = () => {
    setDraft(prev => ({
      ...prev,
      projectBackground: [...prev.projectBackground, ''],
    }))
  }

  const removeBackgroundParagraph = (index) => {
    setDraft(prev => ({
      ...prev,
      projectBackground: prev.projectBackground.filter((_, i) => i !== index),
    }))
  }

  const updateLead = (field, value) => {
    setDraft(prev => ({ ...prev, lead: { ...prev.lead, [field]: value } }))
  }

  const uploadLeadAvatar = async (file) => {
    if (!file) return
    if (file.size > 5 * 1024 * 1024) {
      alert('头像文件不能超过 5MB')
      return
    }
    const formData = new FormData()
    formData.append('avatar', file)
    try {
      const res = await api.post('/api/about/leader-avatar', formData)
      updateLead('avatarUrl', res.data?.avatarUrl || '')
      alert('负责人头像已上传')
    } catch (err) {
      alert(err.response?.data?.error || '头像上传失败')
    }
  }

  const updateTeamField = (teamIndex, field, value) => {
    setDraft(prev => {
      const next = [...prev.teams]
      next[teamIndex] = { ...next[teamIndex], [field]: value }
      return { ...prev, teams: next }
    })
  }

  const addTeam = () => {
    setDraft(prev => ({
      ...prev,
      teams: [
        ...prev.teams,
        { id: `team-${Date.now()}`, title: '新团队', description: '', members: [] },
      ],
    }))
  }

  const removeTeam = (teamIndex) => {
    setDraft(prev => ({
      ...prev,
      teams: prev.teams.filter((_, i) => i !== teamIndex),
    }))
  }

  const addTeamMember = (teamIndex) => {
    setDraft(prev => {
      const next = [...prev.teams]
      const members = Array.isArray(next[teamIndex].members) ? next[teamIndex].members : []
      next[teamIndex] = {
        ...next[teamIndex],
        members: [...members, { name: '', role: '', bio: '' }],
      }
      return { ...prev, teams: next }
    })
  }

  const updateTeamMember = (teamIndex, memberIndex, field, value) => {
    setDraft(prev => {
      const next = [...prev.teams]
      const members = [...(next[teamIndex].members || [])]
      members[memberIndex] = { ...members[memberIndex], [field]: value }
      next[teamIndex] = { ...next[teamIndex], members }
      return { ...prev, teams: next }
    })
  }

  const removeTeamMember = (teamIndex, memberIndex) => {
    setDraft(prev => {
      const next = [...prev.teams]
      next[teamIndex] = {
        ...next[teamIndex],
        members: (next[teamIndex].members || []).filter((_, i) => i !== memberIndex),
      }
      return { ...prev, teams: next }
    })
  }

  const updateVersion = (versionIndex, field, value) => {
    setDraft(prev => {
      const next = [...prev.versionUpdates]
      next[versionIndex] = { ...next[versionIndex], [field]: value }
      return { ...prev, versionUpdates: next }
    })
  }

  const addVersion = () => {
    setDraft(prev => ({
      ...prev,
      versionUpdates: [
        { version: '', date: '', updates: '' },
        ...prev.versionUpdates,
      ],
    }))
  }

  const removeVersion = (versionIndex) => {
    setDraft(prev => ({
      ...prev,
      versionUpdates: prev.versionUpdates.filter((_, i) => i !== versionIndex),
    }))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await api.patch('/api/about/content', { content: draft })
      const saved = normalizeContent(res.data?.content)
      setContent(saved)
      setDraft(saved)
      setMeta({
        updatedBy: res.data?.updatedBy || '',
        updatedAt: res.data?.updatedAt || '',
      })
      setEditMode(false)
      alert('关于我们内容已保存')
    } catch (err) {
      alert(err.response?.data?.error || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const view = editMode ? draft : content

  if (loading) {
    return <div className="page-loading">加载中...</div>
  }

  return (
    <div className="about-page">
      <section className="about-hero">
        <div className="about-hero-pattern" />
        <div className="about-hero-content">
          <span className="about-badge">{view.hero.badge}</span>
          <h1>{view.hero.title}</h1>
          <p>{view.hero.subtitle}</p>
        </div>
      </section>

      {canEdit && (
        <div className="about-edit-bar">
          <button className={`btn btn-sm ${editMode ? 'btn-outline' : 'btn-primary'}`} onClick={() => setEditMode(v => !v)}>
            {editMode ? '退出编辑' : '编辑关于我们'}
          </button>
          {editMode && (
            <button className="btn btn-sm btn-primary" disabled={saving} onClick={handleSave}>
              {saving ? '保存中...' : '保存修改'}
            </button>
          )}
          {meta.updatedBy && <span className="about-edit-meta">最近更新：{meta.updatedBy}</span>}
        </div>
      )}

      {user?.isAdmin && !canEdit && (
        <div className="about-edit-hint">
          当前是管理员账号，但未命中“{ABOUT_EDITOR_USERNAME}”编辑身份（按账号名或昵称判断）。
        </div>
      )}

      <div className="about-anchor-nav">
        <a href="#project-background">项目背景</a>
        <a href="#team">运营团队</a>
        <a href="#version-updates">版本更新</a>
      </div>

      <section id="project-background" className="about-section">
        <h2>项目背景</h2>
        <div className="about-card">
          {view.projectBackground.map((paragraph, index) => (
            <div key={index} className="about-bg-item">
              {editMode ? (
                <div className="about-edit-line">
                  <textarea
                    value={paragraph}
                    onChange={e => updateBackgroundParagraph(index, e.target.value)}
                    placeholder="输入项目背景段落"
                  />
                  <button className="btn btn-sm btn-outline" onClick={() => removeBackgroundParagraph(index)}>删除</button>
                </div>
              ) : (
                <p className="about-bg-paragraph">{paragraph}</p>
              )}
            </div>
          ))}
          {editMode && (
            <button className="btn btn-sm btn-outline" onClick={addBackgroundParagraph}>新增段落</button>
          )}
        </div>
      </section>

      <section id="team-lead" className="about-section">
        <h2>运营团队</h2>
        <div className="about-lead-card">
          <div className="about-lead-avatar">
            {view.lead.avatarUrl ? (
              <img src={view.lead.avatarUrl} alt={view.lead.name || '负责人头像'} />
            ) : (
              <span>{(view.lead.name || '负')[0]}</span>
            )}
          </div>
          <div className="about-lead-main">
            {editMode ? (
              <div className="about-lead-editor">
                <input
                  type="text"
                  value={view.lead.name}
                  onChange={e => updateLead('name', e.target.value)}
                  placeholder="负责人姓名"
                />
                <input
                  type="text"
                  value={view.lead.role}
                  onChange={e => updateLead('role', e.target.value)}
                  placeholder="负责人职能"
                />
                <textarea
                  value={view.lead.experience}
                  onChange={e => updateLead('experience', e.target.value)}
                  placeholder="工作内容"
                />
                <input
                  type="text"
                  value={view.lead.avatarUrl}
                  onChange={e => updateLead('avatarUrl', e.target.value)}
                  placeholder="头像链接（可选）"
                />
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  onChange={e => uploadLeadAvatar(e.target.files?.[0])}
                />
              </div>
            ) : (
              <>
                <h3>{view.lead.name}</h3>
                <p><strong>职能：</strong>{view.lead.role}</p>
                <p><strong>工作内容：</strong>{view.lead.experience}</p>
              </>
            )}
          </div>
        </div>
      </section>

      <section id="team" className="about-section">
        <div className="about-team-grid">
          {view.teams.map((team, teamIndex) => {
            const isOpen = expandedTeams[team.id]
            return (
              <article key={team.id || teamIndex} className="team-card">
                {editMode ? (
                  <div className="about-edit-line">
                    <input
                      type="text"
                      value={team.title || ''}
                      onChange={e => updateTeamField(teamIndex, 'title', e.target.value)}
                      placeholder="团队名称"
                    />
                    <button className="btn btn-sm btn-outline" onClick={() => removeTeam(teamIndex)}>删除团队</button>
                  </div>
                ) : (
                  <h3>{team.title}</h3>
                )}
                {editMode ? (
                  <textarea
                    value={team.description || ''}
                    onChange={e => updateTeamField(teamIndex, 'description', e.target.value)}
                    placeholder="团队职责描述"
                  />
                ) : (
                  <p>{team.description}</p>
                )}
                <button className="team-toggle-btn" onClick={() => toggleTeam(team.id)}>
                  {isOpen ? '收起成员' : '展开成员'}
                </button>

                {isOpen && (
                  <div className="team-members-panel">
                    {(team.members || []).length === 0 && !editMode && (
                      <p className="team-empty-members">暂无公开成员信息</p>
                    )}
                    {(team.members || []).map((member, memberIndex) => (
                      <div key={memberIndex} className="team-member-item">
                        {editMode ? (
                          <>
                            <input
                              type="text"
                              value={member.name || ''}
                              onChange={e => updateTeamMember(teamIndex, memberIndex, 'name', e.target.value)}
                              placeholder="成员姓名"
                            />
                            <input
                              type="text"
                              value={member.role || ''}
                              onChange={e => updateTeamMember(teamIndex, memberIndex, 'role', e.target.value)}
                              placeholder="成员职能"
                            />
                            <textarea
                              value={member.bio || ''}
                              onChange={e => updateTeamMember(teamIndex, memberIndex, 'bio', e.target.value)}
                              placeholder="成员履历"
                            />
                            <button className="btn btn-sm btn-outline" onClick={() => removeTeamMember(teamIndex, memberIndex)}>
                              删除成员
                            </button>
                          </>
                        ) : (
                          <>
                            <div className="team-member-name">{member.name || '未命名成员'}</div>
                            {member.role && <div className="team-member-role">{member.role}</div>}
                            {member.bio && <div className="team-member-bio">{member.bio}</div>}
                          </>
                        )}
                      </div>
                    ))}
                    {editMode && (
                      <button className="btn btn-sm btn-outline" onClick={() => addTeamMember(teamIndex)}>
                        新增成员
                      </button>
                    )}
                  </div>
                )}
              </article>
            )
          })}
        </div>
        {editMode && (
          <button className="btn btn-sm btn-outline" onClick={addTeam}>新增团队</button>
        )}
      </section>

      <section id="version-updates" className="about-section">
        <h2>版本更新</h2>
        {editMode && (
          <div className="about-version-actions">
            <button className="btn btn-sm btn-outline" onClick={addVersion}>新增版本</button>
          </div>
        )}
        <div className="about-timeline">
          {view.versionUpdates.map((item, index) => (
            <div key={`${item.version}-${item.date}-${index}`} className="timeline-item">
              <div className="timeline-dot" />
              <div className="timeline-content">
                {editMode ? (
                  <div className="timeline-editor">
                    <div className="about-edit-line">
                      <input
                        type="text"
                        value={item.version || ''}
                        onChange={e => updateVersion(index, 'version', e.target.value)}
                        placeholder="版本号，如 v1.4"
                      />
                      <input
                        type="text"
                        value={item.date || ''}
                        onChange={e => updateVersion(index, 'date', e.target.value)}
                        placeholder="日期，如 2026-06"
                      />
                      <button className="btn btn-sm btn-outline" onClick={() => removeVersion(index)}>
                        删除
                      </button>
                    </div>
                    <textarea
                      value={item.updates || ''}
                      onChange={e => updateVersion(index, 'updates', e.target.value)}
                      placeholder="版本更新说明"
                    />
                  </div>
                ) : (
                  <>
                    <div className="timeline-head">
                      <strong>{item.version}</strong>
                      <span>{item.date}</span>
                    </div>
                    <p>{item.updates}</p>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
