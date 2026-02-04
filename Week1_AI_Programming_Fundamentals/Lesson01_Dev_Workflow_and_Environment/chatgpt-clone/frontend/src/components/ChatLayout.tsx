import { useCallback } from 'react'
import { Sidebar } from './Sidebar'
import { ModelSelector } from './ModelSelector'
import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'
import { ToastContainer } from './Toast'
import { ParticleBackground } from './ParticleBackground'
import { useChatStore } from '../store/chatStore'
import { useToast } from '../hooks/useToast'
import { streamChat } from '../services/api'

export function ChatLayout() {
  const {
    messages,
    currentConversationId,
    thinkingEnabled,
    addUserMessage,
    startAssistantMessage,
    appendReasoning,
    appendContent,
    finishStreaming,
    createNewConversation,
    loadConversations,
    setAbortController,
    abortStreaming,
  } = useChatStore()

  const { toasts, removeToast, error: showError } = useToast()

  const handleSendMessage = useCallback(async (content: string) => {
    let conversationId = currentConversationId
    if (!conversationId) {
      conversationId = await createNewConversation()
      if (!conversationId) {
        showError('创建对话失败，请重试')
        return
      }
    }
    
    addUserMessage(content)
    startAssistantMessage()
    
    const controller = new AbortController()
    setAbortController(controller)
    
    const apiMessages = [
      ...messages.map((m) => ({
        role: m.role,
        content: m.content,
      })),
      { role: 'user', content },
    ]

    await streamChat(
      {
        messages: apiMessages,
        conversation_id: conversationId,
        thinking_enabled: thinkingEnabled,
      },
      (chunk) => appendReasoning(chunk),
      (chunk) => appendContent(chunk),
      (reasoning, content) => {
        finishStreaming(reasoning, content)
        loadConversations()
      },
      (error) => {
        console.error('Chat error:', error)
        showError(`请求失败: ${error}`)
        finishStreaming(null, '')
      },
      controller.signal
    )
  }, [
    currentConversationId, messages, thinkingEnabled,
    addUserMessage, startAssistantMessage, appendReasoning, 
    appendContent, finishStreaming, createNewConversation, 
    loadConversations, setAbortController, showError
  ])

  const handleStop = useCallback(() => {
    abortStreaming()
  }, [abortStreaming])

  return (
    <div className="relative flex h-screen text-stone-100 overflow-hidden">
      {/* Particle Background */}
      <ParticleBackground />
      
      {/* Gradient Overlay */}
      <div 
        className="absolute inset-0 pointer-events-none z-0"
        style={{
          background: 'radial-gradient(ellipse at top, rgba(249, 115, 22, 0.08) 0%, transparent 50%), radial-gradient(ellipse at bottom right, rgba(245, 158, 11, 0.05) 0%, transparent 50%)'
        }}
      />

      {/* Sidebar */}
      <div className="relative z-10">
        <Sidebar />
      </div>

      {/* Main Chat Area */}
      <div className="relative z-10 flex-1 flex flex-col min-w-0">
        {/* Header with Model Selector */}
        <div className="glass border-b border-stone-800/50 p-4">
          <div className="flex items-center justify-center">
            <ModelSelector />
          </div>
        </div>

        {/* Messages */}
        <MessageList />

        {/* Input */}
        <ChatInput onSend={handleSendMessage} onStop={handleStop} />
      </div>

      {/* Toast notifications */}
      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </div>
  )
}
