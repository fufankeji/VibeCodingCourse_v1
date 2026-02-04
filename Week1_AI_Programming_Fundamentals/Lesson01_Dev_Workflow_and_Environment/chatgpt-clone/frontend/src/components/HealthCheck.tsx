import { useEffect, useState } from 'react'
import { CheckCircle, XCircle, Loader2, RefreshCw } from 'lucide-react'
import type { HealthStatus, Model } from '../types'
import { checkHealth, getModels } from '../services/api'

export function HealthCheck() {
  const [health, setHealth] = useState<HealthStatus>({ status: 'checking' })
  const [models, setModels] = useState<Model[]>([])
  const [isRefreshing, setIsRefreshing] = useState(false)

  const fetchHealth = async () => {
    setIsRefreshing(true)
    setHealth({ status: 'checking' })
    
    const healthResult = await checkHealth()
    setHealth(healthResult)
    
    if (healthResult.status === 'healthy') {
      const modelsResult = await getModels()
      setModels(modelsResult)
    }
    
    setIsRefreshing(false)
  }

  useEffect(() => {
    fetchHealth()
  }, [])

  return (
    <div className="min-h-screen bg-chat-bg flex items-center justify-center p-4">
      <div className="bg-chat-sidebar rounded-2xl shadow-2xl p-8 max-w-md w-full border border-chat-border">
        <h1 className="text-2xl font-bold text-white mb-2 text-center">
          DeepSeek Chat
        </h1>
        <p className="text-gray-400 text-center mb-8">
          系统健康检查
        </p>

        {/* Health Status Card */}
        <div className="bg-chat-input rounded-xl p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <span className="text-gray-300 font-medium">后端服务状态</span>
            <button
              onClick={fetchHealth}
              disabled={isRefreshing}
              className="text-gray-400 hover:text-white transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-5 h-5 ${isRefreshing ? 'animate-spin' : ''}`} />
            </button>
          </div>

          <div className="flex items-center gap-3">
            {health.status === 'checking' && (
              <>
                <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
                <div>
                  <p className="text-white font-medium">检查中...</p>
                  <p className="text-gray-400 text-sm">正在连接后端服务</p>
                </div>
              </>
            )}
            
            {health.status === 'healthy' && (
              <>
                <CheckCircle className="w-8 h-8 text-green-400" />
                <div>
                  <p className="text-white font-medium">服务正常</p>
                  <p className="text-gray-400 text-sm">
                    {health.service} v{health.version}
                  </p>
                </div>
              </>
            )}
            
            {health.status === 'unhealthy' && (
              <>
                <XCircle className="w-8 h-8 text-red-400" />
                <div>
                  <p className="text-white font-medium">连接失败</p>
                  <p className="text-red-400 text-sm">{health.error}</p>
                </div>
              </>
            )}
          </div>

          {health.timestamp && (
            <p className="text-gray-500 text-xs mt-4">
              检查时间: {new Date(health.timestamp).toLocaleString()}
            </p>
          )}
        </div>

        {/* Models List */}
        {health.status === 'healthy' && models.length > 0 && (
          <div className="bg-chat-input rounded-xl p-6">
            <h3 className="text-gray-300 font-medium mb-4">可用模型</h3>
            <div className="space-y-3">
              {models.map((model) => (
                <div
                  key={model.id}
                  className="flex items-center gap-3 p-3 bg-chat-bg rounded-lg"
                >
                  <span className="text-2xl">
                    {model.type === 'reasoning' ? '🧠' : '💬'}
                  </span>
                  <div>
                    <p className="text-white font-medium">{model.name}</p>
                    <p className="text-gray-400 text-sm">{model.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Connection Instructions */}
        {health.status === 'unhealthy' && (
          <div className="bg-red-900/20 border border-red-800 rounded-xl p-4 mt-4">
            <p className="text-red-300 text-sm">
              请确保后端服务正在运行：
            </p>
            <code className="block bg-black/30 rounded p-2 mt-2 text-green-400 text-xs">
              cd backend && uvicorn app.main:app --reload
            </code>
          </div>
        )}
      </div>
    </div>
  )
}
