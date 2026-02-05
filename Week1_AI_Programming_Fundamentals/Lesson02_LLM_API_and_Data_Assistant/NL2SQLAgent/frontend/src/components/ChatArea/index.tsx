import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'
import { useAppStore } from '../../store/useAppStore'
import { useChat } from '../../hooks/useChat'

export function ChatArea() {
  const { messages, currentSessionId } = useAppStore()
  const { sendMessage, isStreaming, abort } = useChat()

  const handleSend = async (content: string) => {
    if (!currentSessionId) {
      // 如果没有会话，useChat 会自动创建
    }
    await sendMessage(content)
  }

  return (
    <div className="flex-1 flex flex-col bg-slate-850 min-w-0">
      {/* 顶部栏 */}
      <div className="h-14 border-b border-slate-700/50 flex items-center justify-between px-6">
        <h2 className="text-sm font-medium text-slate-300">
          {currentSessionId ? '对话' : '选择或创建会话开始'}
        </h2>
        {isStreaming && (
          <button
            onClick={abort}
            className="px-3 py-1 text-xs bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
          >
            停止生成
          </button>
        )}
      </div>

      {/* 消息列表 */}
      <MessageList messages={messages} isStreaming={isStreaming} />

      {/* 输入框 */}
      <ChatInput
        onSend={handleSend}
        disabled={!currentSessionId && useAppStore.getState().sessions.length === 0}
        isStreaming={isStreaming}
      />
    </div>
  )
}
