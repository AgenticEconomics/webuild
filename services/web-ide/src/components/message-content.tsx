'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** Render agent markdown (GFM tables/lists/code). User messages stay plain text. */
export function MessageContent({
  content,
  plain = false,
  className = '',
}: {
  content: string
  plain?: boolean
  className?: string
}) {
  if (!content) return <span className={className}>...</span>
  if (plain) {
    return <div className={`whitespace-pre-wrap break-words ${className}`}>{content}</div>
  }

  return (
    <div className={`markdown-body break-words ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-console-blue underline underline-offset-2 hover:opacity-80">
              {children}
            </a>
          ),
          code: ({ className: cn, children, ...props }) => {
            const isBlock = typeof cn === 'string' && cn.includes('language-')
            if (isBlock) {
              return (
                <code className={`${cn || ''} block`} {...props}>
                  {children}
                </code>
              )
            }
            return (
              <code
                className="px-1 py-0.5 rounded bg-console-bg border border-console-border text-[0.9em] font-mono"
                {...props}
              >
                {children}
              </code>
            )
          },
          pre: ({ children }) => (
            <pre className="my-2 overflow-x-auto rounded border border-console-border bg-console-bg p-3 text-[12px] leading-relaxed font-mono">
              {children}
            </pre>
          ),
          ul: ({ children }) => <ul className="my-2 list-disc pl-5 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal pl-5 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0 leading-relaxed">{children}</p>,
          h1: ({ children }) => <h1 className="mt-3 mb-2 text-base font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="mt-3 mb-2 text-sm font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="mt-2 mb-1 text-sm font-semibold">{children}</h3>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-console-border pl-3 text-console-muted">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded border border-console-border">
              <table className="w-full border-collapse text-left text-[12px]">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-console-bg">{children}</thead>,
          th: ({ children }) => (
            <th className="border-b border-console-border px-2.5 py-1.5 font-medium text-console-muted">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-console-border px-2.5 py-1.5 align-top">{children}</td>
          ),
          hr: () => <hr className="my-3 border-console-border" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
