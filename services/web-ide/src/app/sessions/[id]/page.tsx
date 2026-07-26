'use client'

import { useEffect, useRef, useState } from 'react'
import { Send, Square, Wrench, AlertCircle, CheckCircle2, Clock, Loader2 } from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import { useSessionStore, type Message, type ToolCall } from '@/stores/session-store'

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''} animate-fade-in`}>
      <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-xs font-bold ${
        isUser ? 'bg-indigo-600 text-white' : 'bg-gradient-to-br from-purple-500 to-pink-500 text-white'
      }`}>
        {isUser ? 'U' : 'W'}
      </div>
      <div className={`max-w-[70%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
        isUser
          ? 'bg-indigo-600/90 text-white'
          : 'bg-[#1e1e3a] text-gray-200 border border-[#2a2a4a]'
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
    completed: 'text-emerald-400',
    in_progress: 'text-blue-400',
    failed: 'text-red-400',
    pending: 'text-gray-500',
  }
  const Icon = icons[tc.status] || Wrench
  return (
    <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#16213e] border border-[#2a2a4a] text-xs animate-slide-in`}>
      <Icon className={`w-3 h-3 ${colors[tc.status]} ${tc.status === 'in_progress' ? 'animate-spin' : ''}`} />
      <span className="text-gray-300 truncate max-w-[160px]">{tc.title}</span>
    </div>
  )
}

export default function SessionPage({ params }: { params: { id: string } }) {
  const { messages, toolCalls, activeSessionId, isConnected, connect, sendMessage, cancelCurrent } = useSessionStore()
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
    if (!isConnected) {
      const wsUrl = localStorage.getItem('webuild_ws_url') || `ws://${window.location.host}/ws/relay`
      const token = localStorage.getItem('webuild_token') || ''
      connect(wsUrl, token).catch(() => {})
    }
  }, [isConnected, connect])

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

      <main className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-14 border-b border-[#2a2a4a] flex items-center px-5 flex-shrink-0">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-400">Session</span>
            <span className="text-gray-600">/</span>
            <span className="text-gray-200 font-mono text-xs">{activeSessionId?.slice(0, 8)}...</span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <div className={`flex items-center gap-1.5 text-[11px] ${isConnected ? 'text-emerald-400' : 'text-red-400'}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse-dot' : 'bg-red-400'}`} />
              {isConnected ? 'Connected' : 'Disconnected'}
            </div>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-6 py-8 space-y-5">
            {messages.length === 0 && (
              <div className="text-center py-16">
                <div className="w-12 h-12 mx-auto mb-4 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center opacity-40">
                  <Send className="w-5 h-5 text-white" />
                </div>
                <p className="text-gray-500 text-sm">Start the conversation below</p>
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
        <div className="border-t border-[#2a2a4a] px-6 py-4 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="glass rounded-2xl p-1.5 shadow-lg shadow-black/20">
              <div className="flex items-end gap-2">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={isConnected ? 'Message WeBuild...' : 'Connecting...'}
                  disabled={!isConnected}
                  rows={1}
                  className="flex-1 bg-transparent px-3.5 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none resize-none disabled:opacity-40"
                />
                {sending ? (
                  <button
                    onClick={cancelCurrent}
                    className="p-2.5 rounded-xl bg-red-600/80 hover:bg-red-500 text-white transition-all"
                  >
                    <Square className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    onClick={() => handleSend()}
                    disabled={!input.trim() || !isConnected}
                    className="p-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed active:scale-[0.95]"
                  >
                    <Send className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
            <p className="text-[10px] text-gray-600 text-center mt-2">
              <kbd className="px-1 py-0.5 rounded bg-[#16213e] text-gray-500">Enter</kbd> to send · <kbd className="px-1 py-0.5 rounded bg-[#16213e] text-gray-500">Shift+Enter</kbd> for newline
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
