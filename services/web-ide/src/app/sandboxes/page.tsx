'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Plus, Box, Loader2, Trash2, ExternalLink, Clock } from 'lucide-react'
import { AppShell, NavMenuButton } from '@/components/app-shell'
import { listSandboxes, createSandbox, terminateSandbox, type Sandbox } from '@/lib/gateway-api'
import { createSession } from '@/lib/relay-api'
import { useSessionStore } from '@/stores/session-store'

export default function SandboxesPage() {
  const router = useRouter()
  const [sandboxes, setSandboxes] = useState<Sandbox[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const fetchSandboxes = async () => {
    try {
      const data = await listSandboxes()
      setSandboxes(data)
      setError('')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchSandboxes() }, [])

  const handleCreate = async () => {
    setCreating(true)
    try {
      const session = await createSession()
      const sessionId = session.session_id
      useSessionStore.getState().upsertSession({
        sessionId,
        status: session.status || 'created',
        sandboxId: sessionId,
      })
      const sb = await createSandbox('default', sessionId)
      router.push(`/sandboxes/${sb.id}`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setCreating(false)
    }
  }

  const handleTerminate = async (id: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm('Terminate this sandbox?')) return
    try {
      await terminateSandbox(id)
      fetchSandboxes()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const formatTime = (iso: string) => {
    try { return new Date(iso).toLocaleString() } catch { return iso }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'text-emerald-400 bg-emerald-400/10'
      case 'creating': return 'text-amber-400 bg-amber-400/10'
      case 'terminated': return 'text-zinc-500 bg-zinc-500/10'
      default: return 'text-zinc-400 bg-zinc-400/10'
    }
  }

  return (
    <AppShell>
      <main className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-console-bg">
        <header className="sticky top-0 z-10 flex h-14 items-center gap-2 border-b border-console-border bg-console-surface px-3 sm:px-6">
          <NavMenuButton />
          <h1 className="text-sm font-medium text-console-ink">Sandboxes</h1>
        </header>

        <div className="mx-auto max-w-3xl px-4 py-6 sm:px-8 sm:py-10">
          <div className="mb-6 flex flex-col gap-4 sm:mb-8 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-xl font-semibold text-console-ink sm:text-2xl">Cloud Sandboxes</h1>
              <p className="mt-1 text-sm text-console-muted">Isolated cloud environments powered by ACS Serverless</p>
            </div>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="console-btn-primary w-full disabled:opacity-50 sm:w-auto"
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              New Sandbox
            </button>
          </div>

          {error && (
            <div className="mb-4 rounded border border-console-danger/30 bg-console-danger-soft p-3 text-sm text-console-danger">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-6 w-6 animate-spin text-console-faint" />
            </div>
          ) : sandboxes.length === 0 ? (
            <div className="py-20 text-center">
              <Box className="mx-auto mb-3 h-12 w-12 text-console-border" />
              <p className="text-sm text-console-muted">No sandboxes yet</p>
              <p className="mt-1 text-xs text-console-faint">Create one to get started</p>
            </div>
          ) : (
            <div className="space-y-2">
              {sandboxes.map((sb) => (
                <Link
                  key={sb.id}
                  href={`/sandboxes/${sb.id}`}
                  className="console-card group block p-4 transition-all hover:border-console-blue hover:shadow-console"
                >
                  <div className="flex items-start gap-3 sm:items-center">
                    <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded bg-console-blue-soft">
                      <Box className="h-5 w-5 text-console-blue" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate font-mono text-sm font-medium text-console-ink">{sb.id}</span>
                        <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${getStatusColor(sb.status)}`}>
                          {sb.status}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-console-faint">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatTime(sb.created_at)}
                        </span>
                        <span className="truncate">Pod: {sb.pod_name || '—'}</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 sm:hidden">
                        <Link
                          href={`/sessions/${sb.id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="rounded border border-console-border px-2 py-1 text-[11px] text-console-muted"
                        >
                          Session
                        </Link>
                        {sb.status !== 'terminated' && (
                          <button
                            onClick={(e) => handleTerminate(sb.id, e)}
                            className="rounded border border-console-border px-2 py-1 text-[11px] text-console-danger"
                          >
                            Terminate
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="hidden items-center gap-2 opacity-0 transition-opacity group-hover:opacity-100 sm:flex">
                      <Link
                        href={`/sessions/${sb.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="rounded px-2 py-1 text-[11px] text-console-muted transition-colors hover:bg-console-bg hover:text-console-ink"
                        title="Open linked session"
                      >
                        Session
                      </Link>
                      {sb.status !== 'terminated' && (
                        <button
                          onClick={(e) => handleTerminate(sb.id, e)}
                          className="rounded p-2 text-console-muted transition-colors hover:bg-console-danger-soft hover:text-console-danger"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                      <ExternalLink className="h-4 w-4 text-console-faint" />
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </main>
    </AppShell>
  )
}
