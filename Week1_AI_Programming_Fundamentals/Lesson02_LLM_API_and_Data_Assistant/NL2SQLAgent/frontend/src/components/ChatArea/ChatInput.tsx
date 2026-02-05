import { useState, useRef, useEffect } from 'react'
import { Send, Loader2 } from 'lucide-react'

interface ChatInputProps {
  onSend: (message: string) => void
  disabled?: boolean
  isStreaming?: boolean
}

export function ChatInput({ onSend, disabled, isStreaming }: ChatInputProps) {
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 自动调整高度
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
    }
  }, [input])

  const handleSubmit = () => {
    const trimmed = input.trim()
    if (trimmed && !disabled && !isStreaming) {
      onSend(trimmed)
      setInput('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="border-t border-slate-700/50 bg-slate-900/50 backdrop-blur-sm p-4">
      <div className="max-w-3xl mx-auto">
        <div className="relative flex items-end gap-3 bg-slate-800 rounded-xl border border-slate-700/50 focus-within:border-blue-500/50 transition-colors">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入您的问题，按 Enter 发送..."
            disabled={disabled || isStreaming}
            rows={1}
            className="
              flex-1 bg-transparent text-white placeholder-slate-500
              px-4 py-3 resize-none outline-none
              disabled:opacity-50 disabled:cursor-not-allowed
            "
          />
          <button
            onClick={handleSubmit}
            disabled={!input.trim() || disabled || isStreaming}
            className="
              m-2 p-2 rounded-lg
              bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700
              text-white disabled:text-slate-500
              transition-colors duration-200
              disabled:cursor-not-allowed
            "
          >
            {isStreaming ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
        <p className="text-xs text-slate-600 text-center mt-2">
          按 Enter 发送，Shift + Enter 换行
        </p>
      </div>
    </div>
  )
}
