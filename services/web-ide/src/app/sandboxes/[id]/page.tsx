'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  ArrowLeft, Box, Clock, Loader2, Trash2, Send, Terminal,
  ScrollText, RefreshCw, ChevronDown, ChevronUp,
} from 'lucide-react'
import { AppShell, NavMenuButton } from '@/components/app-shell'
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
  const [logsOpen, setLogsOpen] = useState(false)
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
      <AppShell>
        <main className="flex min-h-0 flex-1 items-center justify-center bg-console-bg">
          <Loader2 className="h-6 w-6 animate-spin text-console-faint" />
        </main>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-console-bg">
        <header className="flex h-14 flex-shrink-0 items-center gap-2 border-b border-console-border bg-console-surface px-3 sm:gap-3 sm:px-5">
          <NavMenuButton />
          <button
            onClick={() => router.push('/sandboxes')}
            className="text-console-muted transition-colors hover:text-console-ink"
            aria-label="Back to sandboxes"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <Box className="hidden h-4 w-4 flex-shrink-0 text-console-blue sm:block" />
          <span className="min-w-0 truncate font-mono text-xs text-console-ink sm:text-sm">
            {sandbox?.id}
          </span>
          <span className={`flex-shrink-0 rounded px-2 py-0.5 text-[10px] font-medium ${
            sandbox?.status === 'running' ? 'bg-console-success-soft text-console-success' :
            sandbox?.status === 'creating' ? 'bg-console-warn-soft text-console-warn' :
            'bg-console-border text-console-faint'
          }`}>
            {sandbox?.status}
          </span>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <span className={`hidden items-center gap-1.5 text-xs sm:flex ${
              isConnected && connectedSessionId === sandbox?.id ? 'text-console-success' : 'text-console-faint'
            }`}>
              <span className={`h-1.5 w-1.5 rounded-full ${
                isConnected && connectedSessionId === sandbox?.id ? 'bg-console-success animate-pulse-dot' : 'bg-console-border'
              }`} />
              {isConnected && connectedSessionId === sandbox?.id
                ? 'Agent Connected'
                : sandbox?.status === 'creating' ? 'Starting...' : 'Disconnected'}
            </span>
            {sandbox?.status !== 'terminated' && (
              <button
                onClick={handleTerminate}
                className="rounded p-1.5 text-console-muted transition-colors hover:bg-console-danger-soft hover:text-console-danger"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        </header>

        {error && (
          <div className="mx-3 mt-3 rounded border border-console-danger/30 bg-console-danger-soft p-3 text-sm text-console-danger sm:mx-5">
            {error}
          </div>
        )}

        <div className="flex flex-shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-console-border px-3 py-2 text-xs text-console-faint sm:px-5">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {sandbox ? formatTime(sandbox.created_at) : '—'}
          </span>
          <span className="hidden sm:inline">Expires: {sandbox ? formatTime(sandbox.expires_at) : '—'}</span>
          <span className="truncate">Pod: {sandbox?.pod_name || '—'}</span>
        </div>

        <div className="flex-shrink-0 border-b border-console-border">
          <button
            type="button"
            onClick={() => setLogsOpen((v) => !v)}
            className="flex w-full items-center gap-2 px-3 py-2 text-xs text-console-muted transition-colors hover:bg-console-bg hover:text-console-ink sm:px-5"
          >
            <ScrollText className="h-3.5 w-3.5" />
            <span className="font-medium">Pod Logs</span>
            {logsLoading && <Loader2 className="h-3 w-3 animate-spin text-console-faint" />}
            <span className="ml-auto flex items-center gap-2">
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); fetchLogs() }}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); fetchLogs() } }}
                className="rounded p-1 text-console-faint hover:bg-console-border hover:text-console-ink"
                title="Refresh logs"
              >
                <RefreshCw className="h-3 w-3" />
              </span>
              {logsOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </span>
          </button>
          {logsOpen && (
            <div className="px-3 pb-3 sm:px-5">
              {logsError ? (
                <div className="py-2 text-xs text-console-danger">{logsError}</div>
              ) : (
                <pre
                  ref={logsEndRef}
                  className="h-28 overflow-auto whitespace-pre-wrap break-words rounded border border-console-border bg-console-ink/95 p-3 font-mono text-[11px] leading-relaxed text-console-bg sm:h-40"
                >
                  {logs || (logsLoading ? 'Loading logs…' : 'No logs')}
                </pre>
              )}
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="mx-auto max-w-3xl space-y-4 px-3 py-5 sm:px-6 sm:py-6">
            {sandbox?.status === 'creating' && (
              <div className="py-12 text-center sm:py-16">
                <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin text-console-blue" />
                <p className="text-sm text-console-muted">Provisioning sandbox environment...</p>
                <p className="mt-1 text-xs text-console-faint">This typically takes 30-60 seconds.</p>
              </div>
            )}

            {sandbox?.status === 'running' && storeMessages.length === 0 && (
              <div className="py-12 text-center sm:py-16">
                <Terminal className="mx-auto mb-3 h-10 w-10 text-console-border" />
                <p className="text-sm text-console-muted">Sandbox is ready. Send a message to start.</p>
              </div>
            )}

            {storeMessages.map((msg) => (
              <div key={msg.id} className={`flex gap-2 animate-fade-in sm:gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                <div className={`hidden h-7 w-7 flex-shrink-0 items-center justify-center rounded text-[11px] font-medium sm:flex ${
                  msg.role === 'user' ? 'bg-console-blue text-white' : 'bg-console-blue-soft text-console-blue-ink'
                }`}>
                  {msg.role === 'user' ? 'U' : 'S'}
                </div>
                <div className={`max-w-[92%] rounded px-3 py-2.5 text-sm leading-relaxed sm:max-w-[75%] sm:px-4 sm:py-3 ${
                  msg.role === 'user'
                    ? 'bg-console-blue text-white'
                    : 'border border-console-border bg-console-surface text-console-ink shadow-console-sm'
                }`}>
                  <div className="whitespace-pre-wrap break-words">{msg.content || '...'}</div>
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        {sandbox?.status !== 'terminated' && (
          <div className="flex-shrink-0 border-t border-console-border bg-console-surface px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-6 sm:py-4">
            <div className="mx-auto max-w-3xl">
              <div className="console-card p-1.5 shadow-console">
                <div className="flex items-end gap-2">
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={paired ? 'Message sandbox agent...' : 'Waiting for agent...'}
                    disabled={!paired}
                    rows={1}
                    className="min-w-0 flex-1 resize-none bg-transparent px-3 py-2.5 text-sm text-console-ink placeholder:text-console-faint focus:outline-none disabled:opacity-40 sm:px-3.5"
                  />
                  {sending ? (
                    <Loader2 className="m-2.5 h-4 w-4 animate-spin text-console-blue" />
                  ) : (
                    <button
                      onClick={handleSend}
                      disabled={!input.trim() || !paired}
                      className="rounded bg-console-blue p-2.5 text-white transition-colors hover:bg-console-blue-hover disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      <Send className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </AppShell>
  )
}
