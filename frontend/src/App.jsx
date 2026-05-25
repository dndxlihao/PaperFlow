import { Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import api from './api'
import Navbar from './components/Navbar'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import PaperLibrary from './pages/PaperLibrary'
import Recommendations from './pages/Recommendations'
import PaperDetail from './pages/PaperDetail'
import KnowledgeBase from './pages/KnowledgeBase'
import ScholarGraph from './pages/ScholarGraph'
import SystemLibrary from './pages/SystemLibrary'
import CreatorStudio from './pages/CreatorStudio'
import Friends from './pages/Friends'
import AdminDashboard from './pages/AdminDashboard'
import About from './pages/About'
import UserProfile from './pages/UserProfile'

function ProtectedRoute({ user, children }) {
  if (!user) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (token) {
      api.get('/api/auth/me')
        .then(res => setUser(res.data))
        .catch(() => localStorage.removeItem('token'))
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const handleLogin = (token, userData) => {
    localStorage.setItem('token', token)
    setUser(userData)
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    setUser(null)
  }

  const handleUserUpdate = (userData) => {
    setUser(userData)
  }

  if (loading) {
    return <div className="loading-screen">加载中...</div>
  }

  return (
    <div className="app">
      <Navbar user={user} onLogout={handleLogout} onUserUpdate={handleUserUpdate} />
      <main className="main-content">
        <Routes>
          <Route path="/login" element={
            user ? <Navigate to="/" replace /> : <Login onLogin={handleLogin} />
          } />
          <Route path="/register" element={
            user ? <Navigate to="/" replace /> : <Register onLogin={handleLogin} />
          } />
          <Route path="/" element={
            <ProtectedRoute user={user}>
              <Dashboard />
            </ProtectedRoute>
          } />
          <Route path="/library" element={
            <ProtectedRoute user={user}>
              <PaperLibrary />
            </ProtectedRoute>
          } />
          <Route path="/recommendations" element={
            <ProtectedRoute user={user}>
              <Recommendations />
            </ProtectedRoute>
          } />
          <Route path="/knowledge" element={
            <ProtectedRoute user={user}>
              <KnowledgeBase />
            </ProtectedRoute>
          } />
          <Route path="/scholars" element={
            <ProtectedRoute user={user}>
              <ScholarGraph />
            </ProtectedRoute>
          } />
          <Route path="/system-library" element={
            <ProtectedRoute user={user}>
              <SystemLibrary user={user} />
            </ProtectedRoute>
          } />
          <Route path="/creator-studio" element={
            <ProtectedRoute user={user}>
              <CreatorStudio />
            </ProtectedRoute>
          } />
          <Route path="/friends" element={
            <ProtectedRoute user={user}>
              <Friends />
            </ProtectedRoute>
          } />
          <Route path="/about" element={
            <ProtectedRoute user={user}>
              <About user={user} />
            </ProtectedRoute>
          } />
          <Route path="/users/:userId" element={
            <ProtectedRoute user={user}>
              <UserProfile />
            </ProtectedRoute>
          } />
          <Route path="/admin" element={
            <ProtectedRoute user={user}>
              {user?.isAdmin ? <AdminDashboard /> : <Navigate to="/" replace />}
            </ProtectedRoute>
          } />
          <Route path="/paper/:articleNumber" element={
            <ProtectedRoute user={user}>
              <PaperDetail />
            </ProtectedRoute>
          } />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
