import { useEffect } from 'react'
import { Plus, MessageSquare, Trash2, PanelLeftClose, PanelLeft, Brain, Loader2, Flame } from 'lucide-react'
import { useChatStore } from '../store/chatStore'

export function Sidebar() {
  const {
    conversations,
    currentConversationId,
    sidebarOpen,
    setSidebarOpen,
    loadConversations,
    switchConversation,
    deleteConversation,
    isStreaming,
    clearCurrentChat,
  } = useChatStore()

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  const handleNewChat = async () => {
    if (isStreaming) return
    clearCurrentChat()
  }

  const handleSwitch = async (id: string) => {
    if (isStreaming || id === currentConversationId) return
    await switchConversation(id)
  }

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    if (isStreaming) return
    await deleteConversation(id)
  }

  if (!sidebarOpen) {
    return (
      <button
        onClick={() => setSidebarOpen(true)}
        className="fixed top-4 left-4 z-50 p-3 rounded-xl glass hover:bg-white/10 transition-all duration-300 btn-glow"
      >
        <PanelLeft className="w-5 h-5 text-orange-400" />
      </button>
    )
  }

  return (
    <div className="w-72 flex flex-col h-full glass border-r border-stone-800/50">
      {/* Header */}
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
              <Flame className="w-4 h-4 text-white" />
            </div>
            <span className="font-bold text-gradient">DeepSeek</span>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          >
            <PanelLeftClose className="w-5 h-5 text-stone-400" />
          </button>
        </div>
        
        <button
          onClick={handleNewChat}
          disabled={isStreaming}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl transition-all duration-300 disabled:opacity-50 bg-gradient-to-r from-orange-600/20 to-amber-600/20 hover:from-orange-600/30 hover:to-amber-600/30 border border-orange-500/20 hover:border-orange-500/40 btn-glow"
        >
          <Plus className="w-4 h-4 text-orange-400" />
          <span className="text-sm font-medium">新对话</span>
        </button>
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        <div className="text-xs text-stone-500 px-2 mb-3 font-medium uppercase tracking-wider">
          历史对话
        </div>
        {conversations.length === 0 ? (
          <div className="text-center py-12">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-orange-500/10 to-amber-500/10 flex items-center justify-center">
              <MessageSquare className="w-8 h-8 text-stone-600" />
            </div>
            <p className="text-stone-500 text-sm">暂无对话记录</p>
            <p className="text-stone-600 text-xs mt-1">开始新的对话吧</p>
          </div>
        ) : (
          <div className="space-y-1">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => handleSwitch(conv.id)}
                className={`
                  group flex items-center gap-3 px-3 py-3 rounded-xl cursor-pointer transition-all duration-300
                  ${currentConversationId === conv.id
                    ? 'bg-gradient-to-r from-orange-600/20 to-amber-600/20 border border-orange-500/30'
                    : 'hover:bg-white/5 border border-transparent'
                  }
                `}
              >
                <div className={`
                  p-2 rounded-lg transition-colors
                  ${conv.thinking_enabled === 'true' 
                    ? 'bg-orange-500/20 text-orange-400' 
                    : 'bg-amber-500/20 text-amber-400'
                  }
                `}>
                  {conv.thinking_enabled === 'true' ? (
                    <Brain className="w-4 h-4" />
                  ) : (
                    <MessageSquare className="w-4 h-4" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <span className="text-sm truncate block text-stone-200">{conv.title}</span>
                  <span className="text-xs text-stone-500">
                    {conv.thinking_enabled === 'true' ? '推理模式' : '快速模式'}
                  </span>
                </div>
                <button
                  onClick={(e) => handleDelete(e, conv.id)}
                  className="opacity-0 group-hover:opacity-100 p-2 hover:bg-red-500/20 rounded-lg transition-all"
                >
                  <Trash2 className="w-4 h-4 text-red-400" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-stone-800/50">
        {isStreaming && (
          <div className="flex items-center gap-2 text-sm text-orange-400 mb-3 px-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="animate-pulse">AI 正在思考...</span>
          </div>
        )}
        <div className="text-xs text-stone-600 text-center">
          Powered by DeepSeek API
        </div>
      </div>
    </div>
  )
}
