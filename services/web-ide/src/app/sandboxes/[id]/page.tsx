'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  ArrowLeft, Box, Clock, Loader2, Trash2, Send, Terminal,
  ScrollText, RefreshCw, ChevronDown, ChevronUp,
} from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import {
  getSandbox, terminateSandbox, getSandboxLogs, type Sandbox,
} from '@/lib/gateway-api'
import { useSessionStore, defaultWsUrl } from '@/stores/session-store'

export default function SandboxDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter()
  const [sandbox, setSandbox] = useState<Sandbox | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const { isConnected, connectedSessionId, connect } = useSessionStore()
  const storeMessages = useSessionStore((s) => s.messages)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Logs panel
  const [logs, setLogs] = useState('')
  const [logsOpen, setLogsOpen] = useState(true)
  const [logsLoading, setLogsLoading] = useState(false)
  const [logsError, setLogsError] = useState('')
  const logsEndRef = useRef<HTMLPreElement>(null)

  const fetchSandbox = useCallback(async () => {
    try {
      const data = await getSandbox(params.id)
      setSandbox(data)
      setError('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [params.id])

  const fetchLogs = useCallback(async () => {
    setLogsLoading(true)
    setLogsError('')
    try {
      const text = await getSandboxLogs(params.id, 300)
      setLogs(text || '(no logs yet)')
    } catch (e: any) {
      setLogsError(e.message)
    } finally {
      setLogsLoading(false)
    }
  }, [params.id])

  useEffect(() => {
    fetchSandbox()
    const timer = setInterval(fetchSandbox, 5000)
    return () => clearInterval(timer)
  }, [fetchSandbox])

  useEffect(() => {
    if (sandbox && sandbox.status !== 'terminated') {
      fetchLogs()
      const timer = setInterval(fetchLogs, 4000)
      return () => clearInterval(timer)
    }
  }, [sandbox?.status, fetchLogs])

  useEffect(() => {
    if (sandbox?.status !== 'running' || !sandbox.id) return
    if (isConnected && connectedSessionId === sandbox.id) return

    const storedWsUrl = localStorage.getItem('webuild_ws_url')
    const wsUrl = storedWsUrl || defaultWsUrl()
    const token = localStorage.getItem('webuild_token') || ''
    connect(wsUrl, token, sandbox.id).catch(console.error)
  }, [sandbox?.status, sandbox?.id, isConnected, connectedSessionId, connect])

  useEffect(() => {
    return () => {
      // leave WS up for session pages; only clear if still on this sandbox
    }
  }, [])
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [storeMessages])

  useEffect(() => {
    if (logsOpen && logsEndRef.current) {
      logsEndRef.current.scrollTop = logsEndRef.current.scrollHeight
    }
  }, [logs, logsOpen])

  const handleTerminate = async () => {
    if (!confirm('Terminate this sandbox? This cannot be undone.')) return
    try {
      await terminateSandbox(params.id)
      router.push('/sandboxes')
    } catch (e: any) {
      setError(e.message)
    }
  }

  const paired = isConnected && connectedSessionId === sandbox?.id

  const handleSend = async () => {
    const text = input.trim()
    if (!text || sending || !paired) return
    setInput('')
    setSending(true)
    try {
      await useSessionStore.getState().sendMessage(text)
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

  const formatTime = (iso: string) => {
    try { return new Date(iso).toLocaleString() } catch { return iso }
  }

  if (loading) {
    return (
      <div className="flex h-screen">
        <Sidebar />
        <main className="flex-1 flex items-center justify-center">
          <Loader2 className="w-6 h-6 text-zinc-500 animate-spin" />
        </main>
      </div>
    )
  }

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-14 border-b border-zinc-700/50 flex items-center px-5 flex-shrink-0 gap-3">
          <button onClick={() => router.push('/sandboxes')} className="text-zinc-400 hover:text-white transition-colors">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <Box className="w-4 h-4 text-indigo-400" />
          <span className="text-sm font-mono text-zinc-300">{sandbox?.id}</span>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
            sandbox?.status === 'running' ? 'text-emerald-400 bg-emerald-400/10' :
            sandbox?.status === 'creating' ? 'text-amber-400 bg-amber-400/10' :
            'text-zinc-500 bg-zinc-500/10'
          }`}>
            {sandbox?.status}
          </span>
          {sandbox?.pod_phase && (
            <span className="text-[10px] text-zinc-500">pod: {sandbox.pod_phase}</span>
          )}
          <div className="ml-auto flex items-center gap-3">
            <span className={`flex items-center gap-1.5 text-xs ${
              isConnected && connectedSessionId === sandbox?.id ? 'text-emerald-400' : 'text-zinc-500'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${
                isConnected && connectedSessionId === sandbox?.id ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'
              }`} />
              {isConnected && connectedSessionId === sandbox?.id
                ? 'Agent Connected'
                : sandbox?.status === 'creating' ? 'Starting...' : 'Disconnected'}
            </span>
            {sandbox?.status !== 'terminated' && (
              <button onClick={handleTerminate} className="p-1.5 rounded-lg hover:bg-red-500/10 text-zinc-400 hover:text-red-400 transition-colors">
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
        </header>

        {error && (
          <div className="mx-5 mt-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">{error}</div>
        )}

        {/* Sandbox info bar */}
        <div className="px-5 py-2 border-b border-zinc-800 flex items-center gap-4 text-xs text-zinc-500 flex-shrink-0">
          <span className="flex items-center gap-1"><Clock className="w-3 h-3" />Created: {sandbox ? formatTime(sandbox.created_at) : '—'}</span>
          <span>Expires: {sandbox ? formatTime(sandbox.expires_at) : '—'}</span>
          <span>Pod: {sandbox?.pod_name || '—'}</span>
          <span className="text-zinc-600">Session = Sandbox ID</span>
        </div>

        {/* Logs panel */}
        <div className="border-b border-zinc-800 flex-shrink-0">
          <button
            type="button"
            onClick={() => setLogsOpen((v) => !v)}
            className="w-full px-5 py-2 flex items-center gap-2 text-xs text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40 transition-colors"
          >
            <ScrollText className="w-3.5 h-3.5" />
            <span className="font-medium">Pod Logs</span>
            {logsLoading && <Loader2 className="w-3 h-3 animate-spin text-zinc-500" />}
            <span className="ml-auto flex items-center gap-2">
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); fetchLogs() }}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); fetchLogs() } }}
                className="p-1 rounded hover:bg-zinc-700 text-zinc-500 hover:text-zinc-300"
                title="Refresh logs"
              >
                <RefreshCw className="w-3 h-3" />
              </span>
              {logsOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </span>
          </button>
          {logsOpen && (
            <div className="px-5 pb-3">
              {logsError ? (
                <div className="text-xs text-red-400 py-2">{logsError}</div>
              ) : (
                <pre
                  ref={logsEndRef}
                  className="h-40 overflow-auto rounded-lg bg-black/60 border border-zinc-800 p-3 text-[11px] leading-relaxed font-mono text-zinc-300 whitespace-pre-wrap break-words"
                >
                  {logs || (logsLoading ? 'Loading logs…' : 'No logs')}
                </pre>
              )}
            </div>
          )}
        </div>

        {/* Chat area */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-6 py-6 space-y-4">
            {sandbox?.status === 'creating' && (
              <div className="text-center py-16">
                <Loader2 className="w-8 h-8 text-indigo-400 animate-spin mx-auto mb-3" />
                <p className="text-zinc-400 text-sm">Provisioning sandbox environment...</p>
                <p className="text-zinc-600 text-xs mt-1">This typically takes 30-60 seconds. Watch logs above for progress.</p>
              </div>
            )}

            {sandbox?.status === 'running' && storeMessages.length === 0 && (
              <div className="text-center py-16">
                <Terminal className="w-10 h-10 text-zinc-700 mx-auto mb-3" />
                <p className="text-zinc-400 text-sm">Sandbox is ready. Send a message to start.</p>
              </div>
            )}

            {storeMessages.map((msg) => (
              <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''} animate-fade-in`}>
                <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-[11px] font-bold ${
                  msg.role === 'user' ? 'bg-indigo-600 text-white' : 'bg-gradient-to-br from-purple-500 to-pink-500 text-white'
                }`}>
                  {msg.role === 'user' ? 'U' : 'S'}
                </div>
                <div className={`max-w-[70%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  msg.role === 'user' ? 'bg-indigo-600/90 text-white' : 'bg-zinc-800 text-zinc-200 border border-zinc-700/50'
                }`}>
                  <div className="whitespace-pre-wrap break-words">{msg.content || '...'}</div>
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input */}
        {sandbox?.status !== 'terminated' && (
          <div className="border-t border-zinc-700/50 px-6 py-4 flex-shrink-0">
            <div className="max-w-3xl mx-auto">
              <div className="bg-zinc-800/60 backdrop-blur rounded-2xl p-1.5 border border-zinc-700/30">
                <div className="flex items-end gap-2">
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={paired ? 'Message sandbox agent...' : 'Waiting for agent...'}
                    disabled={!paired}
                    rows={1}
                    className="flex-1 bg-transparent px-3.5 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none resize-none disabled:opacity-40"
                  />
                  {sending ? (
                    <Loader2 className="w-4 h-4 text-indigo-400 animate-spin p-2" />
                  ) : (
                    <button
                      onClick={handleSend}
                      disabled={!input.trim() || !paired}
                      className="p-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
              <p className="text-[10px] text-zinc-600 text-center mt-2">
                Press <kbd className="px-1 py-0.5 rounded bg-zinc-800 text-zinc-500">Enter</kbd> to send
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
