import { useState, useRef, useEffect } from 'react'
import { Send, Square, Loader2, Sparkles, Brain, Zap } from 'lucide-react'
import { useChatStore } from '../store/chatStore'

interface ChatInputProps {
  onSend: (content: string) => void
  onStop?: () => void
}

export function ChatInput({ onSend, onStop }: ChatInputProps) {
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { isStreaming, thinkingEnabled, streamingReasoning, streamingContent } = useChatStore()

  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px'
    }
  }, [input])

  useEffect(() => {
    if (!isStreaming && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [isStreaming])

  const handleSubmit = () => {
    if (!input.trim() || isStreaming) return
    onSend(input.trim())
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const getStreamingStatus = () => {
    if (!isStreaming) return null
    if (thinkingEnabled && !streamingContent && streamingReasoning) {
      return { icon: Brain, text: '深度思考中...', color: 'text-orange-400' }
    }
    return { icon: Sparkles, text: '生成回复中...', color: 'text-amber-400' }
  }

  const streamingStatus = getStreamingStatus()

  return (
    <div className="relative border-t border-stone-800/50 p-6 glass">
      <div className="max-w-3xl mx-auto">
        {/* Streaming status */}
        {isStreaming && streamingStatus && (
          <div className="flex items-center gap-3 mb-4">
            <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-gradient-to-r from-orange-500/10 to-amber-500/10 border border-orange-500/20">
              <Loader2 className={`w-4 h-4 animate-spin ${streamingStatus.color}`} />
              <streamingStatus.icon className={`w-4 h-4 ${streamingStatus.color}`} />
              <span className={`text-sm ${streamingStatus.color}`}>{streamingStatus.text}</span>
            </div>
          </div>
        )}

        {/* Input container */}
        <div 
          className={`
            relative rounded-2xl transition-all duration-300
            ${isStreaming 
              ? 'border-orange-500/30' 
              : 'border-stone-700/50 focus-within:border-orange-500/50'
            }
          `}
        >
          {/* Gradient border effect */}
          <div className="absolute inset-0 rounded-2xl gradient-border opacity-0 focus-within:opacity-100 transition-opacity duration-300 pointer-events-none" />
          
          <div className="relative glass rounded-2xl overflow-hidden">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                thinkingEnabled
                  ? '输入问题，AI 将展示完整思考过程...'
                  : '输入消息，开始对话...'
              }
              disabled={isStreaming}
              rows={1}
              className="w-full bg-transparent text-stone-100 placeholder-stone-500 px-5 py-4 pr-24 resize-none focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ maxHeight: '200px' }}
            />
            
            <div className="absolute right-3 bottom-3 flex items-center gap-2">
              {isStreaming ? (
                <button
                  onClick={onStop}
                  className="flex items-center gap-2 px-4 py-2.5 bg-red-500 hover:bg-red-600 rounded-xl transition-all duration-300 btn-glow"
                >
                  <Square className="w-4 h-4 text-white fill-white" />
                  <span className="text-white text-sm font-medium">停止</span>
                </button>
              ) : (
                <button
                  onClick={handleSubmit}
                  disabled={!input.trim()}
                  className={`
                    p-3 rounded-xl transition-all duration-300
                    ${input.trim()
                      ? 'bg-gradient-to-r from-orange-500 to-amber-500 hover:from-orange-600 hover:to-amber-600 btn-glow glow-orange'
                      : 'bg-stone-700/50 cursor-not-allowed'
                    }
                  `}
                >
                  <Send className={`w-5 h-5 ${input.trim() ? 'text-white' : 'text-stone-500'}`} />
                </button>
              )}
            </div>
          </div>
        </div>
        
        {/* Mode indicator */}
        <div className="flex items-center justify-center gap-2 mt-4">
          {thinkingEnabled ? (
            <>
              <Brain className="w-4 h-4 text-orange-400" />
              <span className="text-xs text-orange-400">推理模式</span>
              <span className="text-xs text-stone-600">·</span>
              <span className="text-xs text-stone-500">AI 将展示完整思考过程</span>
            </>
          ) : (
            <>
              <Zap className="w-4 h-4 text-amber-400" />
              <span className="text-xs text-amber-400">快速模式</span>
              <span className="text-xs text-stone-600">·</span>
              <span className="text-xs text-stone-500">Enter 发送 · Shift+Enter 换行</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
