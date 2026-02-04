import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import { Copy, Check } from 'lucide-react'
import { useState } from 'react'
import 'highlight.js/styles/github-dark.css'

interface MarkdownContentProps {
  content: string
}

function CodeBlock({ children, className }: { children: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  const language = className?.replace('language-', '') || ''

  const handleCopy = async () => {
    await navigator.clipboard.writeText(children)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="relative group my-4">
      <div className="absolute right-2 top-2 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        {language && (
          <span className="text-xs text-gray-500 bg-gray-800 px-2 py-1 rounded">
            {language}
          </span>
        )}
        <button
          onClick={handleCopy}
          className="p-1.5 rounded bg-gray-700 hover:bg-gray-600 transition-colors"
        >
          {copied ? (
            <Check className="w-4 h-4 text-green-400" />
          ) : (
            <Copy className="w-4 h-4 text-gray-400" />
          )}
        </button>
      </div>
      <pre className={`${className} rounded-lg overflow-x-auto`}>
        <code>{children}</code>
      </pre>
    </div>
  )
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="prose prose-invert max-w-none">
      <ReactMarkdown
        rehypePlugins={[rehypeHighlight]}
        components={{
          code({ className, children, ...props }) {
            const isInline = !className
            if (isInline) {
              return (
                <code className="bg-gray-700 px-1.5 py-0.5 rounded text-sm" {...props}>
                  {children}
                </code>
              )
            }
            return (
              <CodeBlock className={className}>
                {String(children).replace(/\n$/, '')}
              </CodeBlock>
            )
          },
          p({ children }) {
            return <p className="mb-4 leading-relaxed">{children}</p>
          },
          ul({ children }) {
            return <ul className="list-disc list-inside mb-4 space-y-1">{children}</ul>
          },
          ol({ children }) {
            return <ol className="list-decimal list-inside mb-4 space-y-1">{children}</ol>
          },
          h1({ children }) {
            return <h1 className="text-2xl font-bold mb-4 mt-6">{children}</h1>
          },
          h2({ children }) {
            return <h2 className="text-xl font-bold mb-3 mt-5">{children}</h2>
          },
          h3({ children }) {
            return <h3 className="text-lg font-bold mb-2 mt-4">{children}</h3>
          },
          blockquote({ children }) {
            return (
              <blockquote className="border-l-4 border-gray-500 pl-4 italic text-gray-400 my-4">
                {children}
              </blockquote>
            )
          },
          a({ children, href }) {
            return (
              <a href={href} className="text-blue-400 hover:underline" target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
