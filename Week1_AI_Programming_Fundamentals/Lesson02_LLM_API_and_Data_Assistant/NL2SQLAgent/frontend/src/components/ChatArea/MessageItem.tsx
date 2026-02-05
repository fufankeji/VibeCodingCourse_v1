import { User, Bot, Code } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import type { Message } from '../../types'

interface MessageItemProps {
  message: Message
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex gap-4 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* 头像 */}
      <div
        className={`
          w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0
          ${isUser
            ? 'bg-blue-500/20 text-blue-400'
            : 'bg-purple-500/20 text-purple-400'
          }
        `}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      {/* 消息内容 */}
      <div
        className={`
          max-w-[80%] rounded-2xl px-4 py-3
          ${isUser
            ? 'bg-blue-600 text-white'
            : 'bg-slate-800 text-slate-200'
          }
        `}
      >
        {/* Markdown 渲染 */}
        <div className="prose prose-sm prose-invert max-w-none">
          <ReactMarkdown
            components={{
              // 自定义代码块样式
              code({ className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || '')
                const isInline = !match
                
                if (isInline) {
                  return (
                    <code
                      className="bg-slate-700/50 px-1.5 py-0.5 rounded text-sm"
                      {...props}
                    >
                      {children}
                    </code>
                  )
                }
                
                return (
                  <div className="relative my-2">
                    <div className="absolute top-0 right-0 px-2 py-1 text-xs text-slate-500 bg-slate-800 rounded-bl">
                      {match[1]}
                    </div>
                    <pre className="bg-slate-900 rounded-lg p-4 overflow-x-auto">
                      <code className="text-sm" {...props}>
                        {children}
                      </code>
                    </pre>
                  </div>
                )
              },
              // 段落
              p({ children }) {
                return <p className="mb-2 last:mb-0">{children}</p>
              },
              // 列表
              ul({ children }) {
                return <ul className="list-disc pl-4 mb-2">{children}</ul>
              },
              ol({ children }) {
                return <ol className="list-decimal pl-4 mb-2">{children}</ol>
              },
            }}
          >
            {message.content}
          </ReactMarkdown>
        </div>

        {/* SQL 展示 */}
        {message.sql_query && (
          <div className="mt-3 pt-3 border-t border-slate-700/50">
            <div className="flex items-center gap-2 text-xs text-slate-400 mb-2">
              <Code className="w-3.5 h-3.5" />
              <span>执行的 SQL</span>
            </div>
            <pre className="bg-slate-900 rounded-lg p-3 overflow-x-auto">
              <code className="text-xs text-green-400">{message.sql_query}</code>
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
