import { useEffect, useState } from 'react'
import { ChatSidebar } from './components/ChatSidebar'
import { ChatArea } from './components/ChatArea'
import { ChartPanel } from './components/ChartPanel'

function App() {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking')

  useEffect(() => {
    const checkBackend = async () => {
      try {
        const response = await fetch('http://localhost:8000/health')
        if (response.ok) {
          setBackendStatus('connected')
        } else {
          setBackendStatus('disconnected')
        }
      } catch {
        setBackendStatus('disconnected')
      }
    }

    checkBackend()
    // 每 30 秒检查一次
    const interval = setInterval(checkBackend, 30000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="h-screen flex bg-slate-900 text-white overflow-hidden">
      {/* 左侧 - 会话管理 */}
      <ChatSidebar />

      {/* 中间 - 聊天区域 */}
      <ChatArea />

      {/* 右侧 - 图表面板 */}
      <ChartPanel />

      {/* 后端状态指示器 */}
      <div className="fixed bottom-4 right-4 z-50">
        {backendStatus === 'checking' && (
          <div className="px-3 py-1.5 bg-slate-800 rounded-full text-slate-400 text-xs flex items-center gap-2">
            <div className="w-2 h-2 bg-yellow-400 rounded-full animate-pulse" />
            检查后端连接...
          </div>
        )}
        {backendStatus === 'connected' && (
          <div className="px-3 py-1.5 bg-green-500/20 rounded-full text-green-400 text-xs flex items-center gap-2">
            <div className="w-2 h-2 bg-green-400 rounded-full" />
            后端已连接
          </div>
        )}
        {backendStatus === 'disconnected' && (
          <div className="px-3 py-1.5 bg-red-500/20 rounded-full text-red-400 text-xs flex items-center gap-2">
            <div className="w-2 h-2 bg-red-400 rounded-full" />
            后端未连接
          </div>
        )}
      </div>
    </div>
  )
}

export default App
