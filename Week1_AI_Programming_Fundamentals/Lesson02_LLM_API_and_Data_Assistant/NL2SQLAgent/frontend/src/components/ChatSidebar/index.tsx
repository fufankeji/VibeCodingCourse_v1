import { Plus, Database, Loader2, RefreshCw } from 'lucide-react'
import { useSession } from '../../hooks/useSession'
import { SessionItem } from './SessionItem'

export function ChatSidebar() {
  const {
    sessions,
    currentSessionId,
    isLoading,
    error,
    loadSessions,
    createSession,
    selectSession,
    deleteSession,
  } = useSession()

  const handleCreateSession = async () => {
    await createSession()
  }

  return (
    <div className="w-64 h-full bg-slate-900 border-r border-slate-700/50 flex flex-col">
      {/* Logo */}
      <div className="p-4 border-b border-slate-700/50">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <Database className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white">数据分析助理</h1>
            <p className="text-xs text-slate-500">NL2SQL Agent</p>
          </div>
        </div>
      </div>

      {/* 新建会话按钮 */}
      <div className="p-3">
        <button
          onClick={handleCreateSession}
          disabled={isLoading}
          className="
            w-full flex items-center justify-center gap-2 px-4 py-2.5
            bg-blue-600 hover:bg-blue-500 disabled:bg-blue-600/50
            text-white text-sm font-medium
            rounded-lg transition-colors duration-200
          "
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Plus className="w-4 h-4" />
          )}
          新建会话
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="mx-3 mb-3 p-2 bg-red-500/20 rounded-lg">
          <p className="text-xs text-red-400">{error}</p>
          <button
            onClick={loadSessions}
            className="flex items-center gap-1 text-xs text-red-300 hover:text-red-200 mt-1"
          >
            <RefreshCw className="w-3 h-3" />
            重试
          </button>
        </div>
      )}

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        {isLoading && sessions.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-6 h-6 text-slate-500 animate-spin" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-slate-500 text-sm">暂无会话</p>
            <p className="text-slate-600 text-xs mt-1">点击上方按钮创建</p>
          </div>
        ) : (
          <div className="space-y-1">
            {sessions.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={session.id === currentSessionId}
                onSelect={() => selectSession(session.id)}
                onDelete={() => deleteSession(session.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* 底部信息 */}
      <div className="p-3 border-t border-slate-700/50">
        <p className="text-xs text-slate-600 text-center">
          Powered by Qwen3 + LangChain
        </p>
      </div>
    </div>
  )
}
