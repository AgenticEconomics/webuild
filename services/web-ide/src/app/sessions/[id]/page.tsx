'use client'

import { useEffect, useRef, useState } from 'react'
import { Send, Square, Wrench, AlertCircle, CheckCircle2, Clock, Loader2 } from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import { LocaleSwitcher } from '@/components/locale-switcher'
import { useI18n } from '@/lib/i18n'
import { useSessionStore, type Message, type ToolCall } from '@/stores/session-store'

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''} animate-fade-in`}>
      <div className={`w-7 h-7 rounded flex items-center justify-center flex-shrink-0 text-[11px] font-medium ${
        isUser ? 'bg-console-blue text-white' : 'bg-console-blue-soft text-console-blue-ink'
      }`}>
        {isUser ? 'U' : 'W'}
      </div>
      <div className={`max-w-[70%] rounded px-4 py-3 text-sm leading-relaxed ${
        isUser
          ? 'bg-console-blue text-white'
          : 'bg-console-surface text-console-ink border border-console-border shadow-console-sm'
      }`}>
        <div className="whitespace-pre-wrap break-words">{message.content || '...'}</div>
      </div>
    </div>
  )
}

function ToolBadge({ tc }: { tc: ToolCall }) {
  const icons: Record<string, typeof Wrench> = {
    completed: CheckCircle2,
    in_progress: Loader2,
    failed: AlertCircle,
    pending: Clock,
  }
  const colors: Record<string, string> = {
    completed: 'text-console-success',
    in_progress: 'text-console-blue',
    failed: 'text-console-danger',
    pending: 'text-console-faint',
  }
  const Icon = icons[tc.status] || Wrench
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded border border-console-border bg-console-surface text-xs animate-slide-in shadow-console-sm">
      <Icon className={`w-3 h-3 ${colors[tc.status]} ${tc.status === 'in_progress' ? 'animate-spin' : ''}`} />
      <span className="text-console-muted truncate max-w-[160px]">{tc.title}</span>
    </div>
  )
}

export default function SessionPage({ params }: { params: { id: string } }) {
  const { messages, toolCalls, activeSessionId, isConnected, connect, sendMessage, cancelCurrent } = useSessionStore()
  const { t } = useI18n()
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (params.id && params.id !== activeSessionId) {
      useSessionStore.setState({ activeSessionId: params.id, messages: [], toolCalls: [] })
    }
  }, [params.id, activeSessionId])

  useEffect(() => {
    if (!isConnected && params.id) {
      const storedWsUrl = localStorage.getItem('webuild_ws_url')
      // Default: connect directly to relay on port 8002 (bypasses Caddy WS proxy issues)
      const host = window.location.hostname
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = storedWsUrl || `${wsProtocol}//${host}/ws/relay`
      const token = localStorage.getItem('webuild_token') || ''
      connect(wsUrl, token, params.id).catch(() => {})
    }
  }, [isConnected, connect, params.id])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolCalls])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + 'px'
    }
  }, [input])

  // Send initial prompt if stored
  useEffect(() => {
    const key = `initial_prompt_${params.id}`
    const prompt = sessionStorage.getItem(key)
    if (prompt) {
      sessionStorage.removeItem(key)
      setTimeout(() => handleSend(prompt), 500)
    }
  }, [params.id])

  const handleSend = async (text?: string) => {
    const msg = text || input.trim()
    if (!msg || sending) return
    if (!text) setInput('')
    setSending(true)
    try {
      await sendMessage(msg)
    } finally {
      setSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-screen">
      <Sidebar />

      <main className="flex-1 flex flex-col min-w-0 bg-console-bg">
        {/* Header */}
        <header className="h-14 border-b border-console-border bg-console-surface flex items-center px-5 flex-shrink-0">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-console-muted">{t('session')}</span>
            <span className="text-console-border-strong">/</span>
            <span className="text-console-ink font-mono text-xs">
              {activeSessionId?.slice(0, 8)}...
            </span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <LocaleSwitcher />
            <div
              className={`flex items-center gap-1.5 text-[11px] ${
                isConnected ? 'text-console-success' : 'text-console-danger'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isConnected ? 'bg-console-success animate-pulse-dot' : 'bg-console-danger'
                }`}
              />
              {isConnected ? t('connected') : t('disconnected')}
            </div>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-6 py-8 space-y-5">
            {messages.length === 0 && (
              <div className="text-center py-16">
                <div className="w-12 h-12 mx-auto mb-4 rounded bg-console-blue-soft flex items-center justify-center">
                  <Send className="w-5 h-5 text-console-blue" />
                </div>
                <p className="text-console-muted text-sm">{t('startConversation')}</p>
              </div>
            )}
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}

            {/* Tool call badges */}
            {toolCalls.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pl-10">
                {toolCalls.slice(-6).map((tc) => (
                  <ToolBadge key={tc.toolCallId} tc={tc} />
                ))}
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input */}
        <div className="border-t border-console-border bg-console-surface px-6 py-4 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="console-card shadow-console p-1.5">
              <div className="flex items-end gap-2">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={isConnected ? t('messagePlaceholder') : t('connecting')}
                  disabled={!isConnected}
                  rows={1}
                  className="flex-1 bg-transparent px-3.5 py-2.5 text-sm text-console-ink placeholder:text-console-faint focus:outline-none resize-none disabled:opacity-40"
                />
                {sending ? (
                  <button
                    onClick={cancelCurrent}
                    className="p-2.5 rounded bg-console-danger text-white hover:opacity-90 transition-opacity"
                  >
                    <Square className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    onClick={() => handleSend()}
                    disabled={!input.trim() || !isConnected}
                    className="p-2.5 rounded bg-console-blue text-white hover:bg-console-blue-hover transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
            <p className="text-[10px] text-console-faint text-center mt-2">
              <kbd className="px-1 py-0.5 rounded border border-console-border bg-console-bg text-console-muted">
                Enter
              </kbd>{' '}
              {t('toSend')} ·{' '}
              <kbd className="px-1 py-0.5 rounded border border-console-border bg-console-bg text-console-muted">
                Shift+Enter
              </kbd>{' '}
              {t('forNewline')}
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
