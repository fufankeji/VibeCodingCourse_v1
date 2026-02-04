import { useState } from 'react'
import { ChevronDown, ChevronRight, Brain, Loader2, Sparkles } from 'lucide-react'

interface ThinkingBlockProps {
  content: string
  isStreaming?: boolean
}

export function ThinkingBlock({ content, isStreaming = false }: ThinkingBlockProps) {
  const [isExpanded, setIsExpanded] = useState(true)

  if (!content && !isStreaming) return null

  return (
    <div className="mb-6 rounded-2xl overflow-hidden border border-orange-500/20 bg-gradient-to-br from-orange-900/20 to-amber-900/20">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-white/5 transition-all duration-300"
      >
        <div className="flex items-center gap-3 text-orange-400">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
          <div className="p-2 rounded-lg bg-orange-500/20">
            <Brain className="w-4 h-4" />
          </div>
          <span className="font-medium">思考过程</span>
        </div>
        
        {isStreaming && (
          <div className="flex items-center gap-2 ml-auto">
            <div className="relative">
              <Loader2 className="w-4 h-4 text-orange-400 animate-spin" />
              <Sparkles className="absolute -top-1 -right-1 w-3 h-3 text-yellow-400 animate-pulse" />
            </div>
            <span className="text-xs text-orange-300 animate-pulse">深度思考中...</span>
          </div>
        )}
        
        {!isStreaming && content && (
          <span className="text-xs text-stone-500 ml-auto px-3 py-1 rounded-full bg-white/5">
            {content.length} 字
          </span>
        )}
      </button>
      
      {/* Content */}
      {isExpanded && (
        <div className="px-5 pb-5">
          <div className="relative">
            {/* Gradient line */}
            <div className="absolute left-0 top-0 bottom-0 w-1 rounded-full bg-gradient-to-b from-orange-500 via-amber-500 to-yellow-500" />
            
            <div className="pl-5 py-3">
              <div 
                className="text-sm text-stone-300 whitespace-pre-wrap leading-relaxed"
                style={{ fontStyle: 'italic' }}
              >
                {content || (
                  <span className="text-stone-500 flex items-center gap-2">
                    <span className="animate-pulse">正在组织思路</span>
                    <span className="flex gap-1">
                      <span className="w-1.5 h-1.5 bg-orange-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-bounce" style={{ animationDelay: '100ms' }} />
                      <span className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-bounce" style={{ animationDelay: '200ms' }} />
                    </span>
                  </span>
                )}
                {isStreaming && content && (
                  <span className="inline-block w-2 h-4 bg-gradient-to-b from-orange-400 to-amber-400 ml-1 animate-pulse rounded-full align-middle" />
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
