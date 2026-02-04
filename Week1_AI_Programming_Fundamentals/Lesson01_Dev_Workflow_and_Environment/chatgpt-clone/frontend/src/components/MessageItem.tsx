import { User, Bot, Brain, Sparkles, Flame } from 'lucide-react'
import type { Message } from '../types'
import { ThinkingBlock } from './ThinkingBlock'
import { MarkdownContent } from './MarkdownContent'
import { useChatStore } from '../store/chatStore'

interface MessageItemProps {
  message: Message
}

export function MessageItem({ message }: MessageItemProps) {
  const { isStreaming, streamingMessageId } = useChatStore()
  const isUser = message.role === 'user'
  const isCurrentlyStreaming = isStreaming && streamingMessageId === message.id
  const hasReasoning = message.reasoning_content !== undefined && message.reasoning_content !== null && message.reasoning_content !== ''

  return (
    <div className={`py-8 transition-colors ${isUser ? '' : 'bg-white/[0.02]'}`}>
      <div className="max-w-3xl mx-auto px-6 flex gap-5">
        {/* Avatar */}
        <div className="relative flex-shrink-0">
          <div className={`
            w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-300
            ${isUser 
              ? 'bg-gradient-to-br from-amber-500 to-yellow-500' 
              : hasReasoning 
                ? 'bg-gradient-to-br from-orange-500 to-red-500 animate-pulse-glow' 
                : 'bg-gradient-to-br from-orange-500 to-amber-500'
            }
          `}>
            {isUser ? (
              <User className="w-5 h-5 text-white" />
            ) : hasReasoning ? (
              <Brain className="w-5 h-5 text-white" />
            ) : (
              <Flame className="w-5 h-5 text-white" />
            )}
          </div>
          {!isUser && isCurrentlyStreaming && (
            <Sparkles className="absolute -top-1 -right-1 w-4 h-4 text-yellow-400 animate-pulse" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Role label */}
          <div className="text-sm font-medium mb-3 flex items-center gap-2">
            {isUser ? (
              <span className="text-amber-400">你</span>
            ) : (
              <>
                <span className="text-gradient">DeepSeek</span>
                {hasReasoning && (
                  <span className="text-xs bg-orange-500/20 text-orange-300 px-2 py-1 rounded-full border border-orange-500/20">
                    🧠 推理模式
                  </span>
                )}
              </>
            )}
          </div>

          {/* Thinking block for reasoning model */}
          {!isUser && (hasReasoning || (isCurrentlyStreaming && message.reasoning_content !== undefined)) && (
            <ThinkingBlock 
              content={message.reasoning_content || ''} 
              isStreaming={isCurrentlyStreaming && !message.content}
            />
          )}

          {/* Message content */}
          <div className="text-stone-200 leading-relaxed">
            {isUser ? (
              <p className="whitespace-pre-wrap">{message.content}</p>
            ) : (
              <>
                {message.content ? (
                  <>
                    <MarkdownContent content={message.content} />
                    {isCurrentlyStreaming && (
                      <span className="inline-block w-2 h-5 bg-gradient-to-b from-orange-400 to-amber-400 ml-1 animate-pulse rounded-full align-middle" />
                    )}
                  </>
                ) : (
                  isCurrentlyStreaming && !hasReasoning && (
                    <div className="flex items-center gap-3">
                      <div className="flex gap-1.5">
                        <div className="w-2.5 h-2.5 bg-orange-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                        <div className="w-2.5 h-2.5 bg-amber-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                        <div className="w-2.5 h-2.5 bg-yellow-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                      <span className="text-stone-400 text-sm">正在生成回复...</span>
                    </div>
                  )
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
