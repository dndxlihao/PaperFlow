import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import api from '../api'
import './Auth.css'

const JOURNAL_OPTIONS = ['IEEE TSG', 'IEEE TSTE', 'IEEE TPWRS', 'IEEE TIE', 'Applied Energy', 'Energy']
const AREA_OPTIONS = ['电力系统', '新能源', '储能', '智能电网', '电力电子', '机器学习']

export default function Register({ onLogin }) {
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    confirm: '',
    journals: [],
    researchAreas: [],
  })
  const [customArea, setCustomArea] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const update = (key, val) => setForm(f => ({ ...f, [key]: val }))

  const toggleValue = (key, val) => {
    setForm(f => {
      const exists = f[key].includes(val)
      return {
        ...f,
        [key]: exists ? f[key].filter(x => x !== val) : [...f[key], val],
      }
    })
  }

  const addCustomArea = (value) => {
    const v = value.trim()
    if (!v) return
    setForm(f => ({
      ...f,
      researchAreas: f.researchAreas.includes(v) ? f.researchAreas : [...f.researchAreas, v],
    }))
    setCustomArea('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.password !== form.confirm) {
      setError('两次输入的密码不一致')
      return
    }
    setLoading(true)
    try {
      const res = await api.post('/api/auth/register', {
        username: form.username,
        email: form.email,
        password: form.password,
        journals: form.journals,
        researchAreas: form.researchAreas,
      })
      onLogin(res.data.token, res.data.user)
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.error || '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-card">
        <h2>注册 PaperFlow</h2>
        <form onSubmit={handleSubmit}>
          {error && <div className="auth-error">{error}</div>}
          <div className="form-group">
            <label>用户名</label>
            <input type="text" value={form.username} onChange={e => update('username', e.target.value)} required autoFocus />
          </div>
          <div className="form-group">
            <label>邮箱</label>
            <input type="email" value={form.email} onChange={e => update('email', e.target.value)} required />
          </div>
          <div className="form-group">
            <label>密码</label>
            <input type="password" value={form.password} onChange={e => update('password', e.target.value)} required minLength={6} />
          </div>
          <div className="form-group">
            <label>确认密码</label>
            <input type="password" value={form.confirm} onChange={e => update('confirm', e.target.value)} required />
          </div>

          <div className="pref-section">
            <h3>订阅偏好（可选）</h3>

            <div className="form-group">
              <label>期刊偏好（可多选）</label>
              <div className="tag-options">
                {JOURNAL_OPTIONS.map(item => (
                  <button
                    key={item}
                    type="button"
                    className={`tag-option ${form.journals.includes(item) ? 'active' : ''}`}
                    onClick={() => toggleValue('journals', item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>

            <div className="form-group">
              <label>研究方向（可多选）</label>
              <div className="tag-options">
                {AREA_OPTIONS.map(item => (
                  <button
                    key={item}
                    type="button"
                    className={`tag-option ${form.researchAreas.includes(item) ? 'active' : ''}`}
                    onClick={() => toggleValue('researchAreas', item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
              <div className="custom-input-row">
                <input
                  type="text"
                  placeholder="添加自定义研究方向"
                  value={customArea}
                  onChange={e => setCustomArea(e.target.value)}
                />
                <button type="button" className="btn btn-outline" onClick={() => addCustomArea(customArea)}>添加</button>
              </div>
            </div>
          </div>

          <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
            {loading ? '注册中...' : '注册'}
          </button>
        </form>
        <p className="auth-switch">
          已有账号？<Link to="/login">去登录</Link>
        </p>
      </div>
    </div>
  )
}
