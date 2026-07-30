'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Send, Square, Wrench, AlertCircle, CheckCircle2, Clock, Loader2, Box, Paperclip, X } from 'lucide-react'
import { AppShell, NavMenuButton } from '@/components/app-shell'
import { LocaleSwitcher } from '@/components/locale-switcher'
import { WorkspaceOutputsPanel } from '@/components/workspace-outputs-panel'
import { useI18n } from '@/lib/i18n'
import { useSessionStore, type Message, type ToolCall, defaultWsUrl } from '@/stores/session-store'
import { getSandbox, uploadSandboxFiles, type Sandbox } from '@/lib/gateway-api'
import { MessageContent } from '@/components/message-content'

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex gap-2 animate-fade-in sm:gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`hidden h-7 w-7 flex-shrink-0 items-center justify-center rounded text-[11px] font-medium sm:flex ${
        isUser ? 'bg-console-blue text-white' : 'bg-console-blue-soft text-console-blue-ink'
      }`}>
        {isUser ? 'U' : 'W'}
      </div>
      <div className={`max-w-[92%] rounded px-3 py-2.5 text-sm leading-relaxed sm:max-w-[75%] sm:px-4 sm:py-3 ${
        isUser
          ? 'bg-console-blue text-white'
          : 'bg-console-surface text-console-ink border border-console-border shadow-console-sm'
      }`}>
        <MessageContent content={message.content || ''} plain={isUser} />
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
  const {
    messages, toolCalls, activeSessionId, isConnected, connectedSessionId,
    acpReady, agentConnected,
    connect, sendMessage, cancelCurrent, setActiveSession, loadHistory, historyLoading,
  } = useSessionStore()
  const { t } = useI18n()
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [sandbox, setSandbox] = useState<Sandbox | null>(null)
  const [sandboxError, setSandboxError] = useState('')
  const [uploadedPaths, setUploadedPaths] = useState<string[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const initialPromptSent = useRef(false)

  useEffect(() => {
    if (params.id) {
      setActiveSession(params.id)
      loadHistory(params.id)
    }
  }, [params.id, setActiveSession, loadHistory])

  useEffect(() => {
    if (!params.id) return
    let cancelled = false
    const poll = async () => {
      try {
        const sb = await getSandbox(params.id)
        if (!cancelled) {
          setSandbox(sb)
          setSandboxError('')
        }
      } catch (e: unknown) {
        if (!cancelled) {
          setSandbox(null)
          setSandboxError(e instanceof Error ? e.message : 'Sandbox unavailable')
        }
      }
    }
    poll()
    const timer = setInterval(poll, 5000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [params.id])

  // Always (re)connect when the URL session changes — previous bug kept the old WS
  useEffect(() => {
    if (!params.id) return
    if (isConnected && connectedSessionId === params.id) return

    const storedWsUrl = localStorage.getItem('webuild_ws_url')
    const wsUrl = storedWsUrl || defaultWsUrl()
    const token = localStorage.getItem('webuild_token') || ''
    connect(wsUrl, token, params.id).catch((e) => {
      console.error('WS connect failed:', e)
    })
  }, [params.id, connectedSessionId, isConnected, connect])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolCalls])

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + 'px'
    }
  }, [input])

  useEffect(() => {
    initialPromptSent.current = false
  }, [params.id])

  useEffect(() => {
    // Wait for ACP handshake (initialize + session/new) — not just WS open
    if (!acpReady || connectedSessionId !== params.id || initialPromptSent.current) return
    const key = `initial_prompt_${params.id}`
    const prompt = sessionStorage.getItem(key)
    if (prompt) {
      sessionStorage.removeItem(key)
      initialPromptSent.current = true
      handleSend(prompt)
    }
  }, [params.id, acpReady, connectedSessionId])

  const handleSend = async (text?: string) => {
    let msg = (text || input).trim()
    if (!msg && uploadedPaths.length === 0) return
    if (sending) return

    if (uploadedPaths.length > 0) {
      const list = uploadedPaths.map((p) => `- /workspace/${p}`).join('\n')
      const hint =
        `[Uploaded files in /workspace/inbox — please process with tools/skills; ` +
        `put final deliverables under /workspace/outputs/]\n${list}`
      msg = msg ? `${msg}\n\n${hint}` : hint
    }

    // Clear composer immediately (same as input) — files already landed in inbox/
    if (!text) setInput('')
    setUploadedPaths([])
    setUploadError('')
    setSending(true)
    setSendError('')
    try {
      await sendMessage(msg)
    } catch (e: unknown) {
      const errMsg = e instanceof Error ? e.message : 'Send failed'
      setSendError(errMsg)
      console.error('send failed:', e)
    } finally {
      setSending(false)
    }
  }

  const handleUpload = async (fileList: FileList | null) => {
    if (!fileList?.length || !params.id) return
    if (sandbox?.status !== 'running') {
      setUploadError(t('outputsNeedSandbox'))
      return
    }
    setUploading(true)
    setUploadError('')
    try {
      const paths = await uploadSandboxFiles(params.id, Array.from(fileList), 'inbox')
      setUploadedPaths((prev) => {
        const set = new Set([...prev, ...paths])
        return Array.from(set)
      })
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : t('uploadFailed'))
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const sandboxProvisioning = sandbox?.status === 'creating'
  const paired = isConnected && connectedSessionId === params.id
  const canSend = paired && acpReady && !sandboxProvisioning
  const sandboxRunning = sandbox?.status === 'running'

  return (
    <AppShell>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-console-bg">
        <header className="flex h-14 flex-shrink-0 items-center gap-2 border-b border-console-border bg-console-surface px-3 sm:gap-3 sm:px-5">
          <NavMenuButton />
          <div className="flex min-w-0 items-center gap-2 text-sm">
            <span className="hidden text-console-muted sm:inline">{t('session')}</span>
            <span className="hidden text-console-border-strong sm:inline">/</span>
            <span className="truncate font-mono text-xs text-console-ink">
              {activeSessionId?.slice(0, 8)}…
            </span>
          </div>
          <div className="ml-auto flex min-w-0 items-center gap-2 sm:gap-3">
            {sandbox && (
              <Link
                href={`/sandboxes/${sandbox.id}`}
                className="flex items-center gap-1.5 text-[11px] text-console-muted transition-colors hover:text-console-ink"
                title="Open linked sandbox"
              >
                <Box className="h-3.5 w-3.5" />
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                  sandbox.status === 'running' ? 'bg-console-success-soft text-console-success' :
                  sandbox.status === 'creating' ? 'bg-console-warn-soft text-console-warn' :
                  'bg-console-border text-console-faint'
                }`}>
                  {sandbox.status}
                </span>
              </Link>
            )}
            <div className="hidden sm:block">
              <LocaleSwitcher />
            </div>
            <div
              className={`flex items-center gap-1.5 text-[11px] ${
                acpReady ? 'text-console-success' :
                paired ? 'text-console-warn' : 'text-console-danger'
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  acpReady ? 'bg-console-success animate-pulse-dot' :
                  paired ? 'bg-console-warn animate-pulse-dot' : 'bg-console-danger'
                }`}
              />
              <span className="hidden max-w-[140px] truncate sm:inline">
                {acpReady
                  ? t('connected')
                  : paired
                    ? (agentConnected ? 'Handshaking…' : 'Waiting for agent…')
                    : t('disconnected')}
              </span>
            </div>
          </div>
        </header>

        {sandboxProvisioning && (
          <div className="flex items-center gap-2 border-b border-console-border bg-console-warn-soft px-3 py-2 text-xs text-console-warn sm:px-5">
            <Loader2 className="h-3.5 w-3.5 flex-shrink-0 animate-spin" />
            <span>Provisioning linked sandbox… Agent will join when ready.</span>
          </div>
        )}

        {paired && !acpReady && !sandboxProvisioning && (
          <div className="flex items-center gap-2 border-b border-console-border bg-console-warn-soft px-3 py-2 text-xs text-console-warn sm:px-5">
            <Loader2 className="h-3.5 w-3.5 flex-shrink-0 animate-spin" />
            <span>
              {agentConnected
                ? 'Agent connected — finishing ACP handshake…'
                : 'Waiting for sandbox agent to connect…'}
            </span>
          </div>
        )}

        {sendError && (
          <div className="border-b border-console-border bg-red-500/10 px-3 py-2 text-xs text-red-400 sm:px-5">
            {sendError}
            {sendError.toLowerCase().includes('agent') && (
              <span className="ml-1">Waiting for sandbox/agent to connect.</span>
            )}
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="mx-auto max-w-3xl space-y-4 px-3 py-5 sm:space-y-5 sm:px-6 sm:py-8">
            {messages.length === 0 && !historyLoading && (
              <div className="py-12 text-center sm:py-16">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded bg-console-blue-soft">
                  <Send className="h-5 w-5 text-console-blue" />
                </div>
                <p className="text-sm text-console-muted">{t('startConversation')}</p>
                {sandbox && (
                  <p className="mt-2 text-xs text-console-faint">
                    Linked sandbox: <span className="font-mono">{sandbox.id.slice(0, 12)}</span>
                  </p>
                )}
                {!sandbox && sandboxError && (
                  <p className="mt-2 text-xs text-console-faint">
                    No cloud sandbox — using lightweight agent if available.
                  </p>
                )}
              </div>
            )}
            {historyLoading && messages.length === 0 && (
              <div className="py-12 text-center sm:py-16">
                <Loader2 className="mx-auto mb-3 h-6 w-6 animate-spin text-console-faint" />
                <p className="text-sm text-console-faint">Loading history…</p>
              </div>
            )}
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}

            {toolCalls.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pl-0 sm:pl-10">
                {toolCalls.slice(-6).map((tc) => (
                  <ToolBadge key={tc.toolCallId} tc={tc} />
                ))}
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>

        <WorkspaceOutputsPanel sandboxId={params.id} enabled={sandboxRunning} />

        <div className="flex-shrink-0 border-t border-console-border bg-console-surface px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-6 sm:py-4">
          <div className="mx-auto max-w-3xl">
            {(uploadedPaths.length > 0 || uploadError) && (
              <div className="mb-2 flex flex-wrap items-center gap-2">
                {uploadedPaths.map((p) => (
                  <span
                    key={p}
                    className="inline-flex max-w-full items-center gap-1 rounded border border-console-border bg-console-bg px-2 py-1 text-[11px] text-console-ink"
                  >
                    <span className="truncate font-mono" title={p}>
                      {p}
                    </span>
                    <button
                      type="button"
                      aria-label={t('removeUpload')}
                      onClick={() => setUploadedPaths((prev) => prev.filter((x) => x !== p))}
                      className="text-console-faint hover:text-console-danger"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                {uploadError && <span className="text-[11px] text-console-danger">{uploadError}</span>}
              </div>
            )}
            <div className="console-card p-1.5 shadow-console">
              <div className="flex items-end gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(e) => handleUpload(e.target.files)}
                />
                <button
                  type="button"
                  title={t('uploadFiles')}
                  disabled={!sandboxRunning || uploading}
                  onClick={() => fileInputRef.current?.click()}
                  className="rounded p-2.5 text-console-muted transition-colors hover:bg-console-bg hover:text-console-ink disabled:cursor-not-allowed disabled:opacity-30"
                >
                  {uploading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Paperclip className="h-4 w-4" />
                  )}
                </button>
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={
                    !paired
                      ? t('connecting')
                      : sandboxProvisioning
                        ? 'Waiting for sandbox…'
                        : t('messagePlaceholder')
                  }
                  disabled={!canSend}
                  rows={1}
                  className="min-w-0 flex-1 resize-none bg-transparent px-3 py-2.5 text-sm text-console-ink placeholder:text-console-faint focus:outline-none disabled:opacity-40 sm:px-3.5"
                />
                {sending ? (
                  <button
                    onClick={cancelCurrent}
                    className="rounded bg-console-danger p-2.5 text-white transition-opacity hover:opacity-90"
                  >
                    <Square className="h-4 w-4" />
                  </button>
                ) : (
                  <button
                    onClick={() => handleSend()}
                    disabled={(!input.trim() && uploadedPaths.length === 0) || !canSend}
                    className="rounded bg-console-blue p-2.5 text-white transition-colors hover:bg-console-blue-hover disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    <Send className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
            <p className="mt-2 hidden text-center text-[10px] text-console-faint sm:block">
              <kbd className="rounded border border-console-border bg-console-bg px-1 py-0.5 text-console-muted">
                Enter
              </kbd>{' '}
              {t('toSend')} ·{' '}
              <kbd className="rounded border border-console-border bg-console-bg px-1 py-0.5 text-console-muted">
                Shift+Enter
              </kbd>{' '}
              {t('forNewline')}
            </p>
          </div>
        </div>
      </main>
    </AppShell>
  )
}
