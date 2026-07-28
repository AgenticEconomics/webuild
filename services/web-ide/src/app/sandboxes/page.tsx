'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Plus, Box, Loader2, Trash2, ExternalLink, Clock } from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
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
      // Session and sandbox share the same id so the agent joins the chat session
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
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-8 py-10">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-2xl font-bold text-white">Cloud Sandboxes</h1>
              <p className="text-sm text-zinc-400 mt-1">Isolated cloud environments powered by ACS Serverless</p>
            </div>
            <button
              onClick={handleCreate}
              disabled={creating}
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-all disabled:opacity-50"
            >
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              New Sandbox
            </button>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="w-6 h-6 text-zinc-500 animate-spin" />
            </div>
          ) : sandboxes.length === 0 ? (
            <div className="text-center py-20">
              <Box className="w-12 h-12 text-zinc-700 mx-auto mb-3" />
              <p className="text-zinc-500 text-sm">No sandboxes yet</p>
              <p className="text-zinc-600 text-xs mt-1">Create one to get started</p>
            </div>
          ) : (
            <div className="space-y-2">
              {sandboxes.map((sb) => (
                <Link
                  key={sb.id}
                  href={`/sandboxes/${sb.id}`}
                  className="block p-4 bg-zinc-800/50 hover:bg-zinc-800 border border-zinc-700/50 rounded-xl transition-all group"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                      <Box className="w-5 h-5 text-indigo-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white font-mono">{sb.id}</span>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${getStatusColor(sb.status)}`}>
                          {sb.status}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs text-zinc-500">
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {formatTime(sb.created_at)}
                        </span>
                        <span>Pod: {sb.pod_name || '—'}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Link
                        href={`/sessions/${sb.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="px-2 py-1 rounded-lg text-[11px] text-zinc-400 hover:text-white hover:bg-zinc-700 transition-colors"
                        title="Open linked session"
                      >
                        Session
                      </Link>
                      {sb.status !== 'terminated' && (
                        <button
                          onClick={(e) => handleTerminate(sb.id, e)}
                          className="p-2 rounded-lg hover:bg-red-500/10 text-zinc-400 hover:text-red-400 transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                      <ExternalLink className="w-4 h-4 text-zinc-500" />
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
