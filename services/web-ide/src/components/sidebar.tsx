'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import {
  Plus, MessageSquare, Settings, Clock, Box, Loader2, Trash2
} from 'lucide-react'
import { useSessionStore } from '@/stores/session-store'
import { startNewSession } from '@/lib/start-session'
import { useI18n } from '@/lib/i18n'
import { LocaleSwitcher } from '@/components/locale-switcher'

export function Sidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const { sessions, isConnected, loadSessions, sessionsLoaded, removeSession } = useSessionStore()
  const { t } = useI18n()
  const [creating, setCreating] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionsLoaded) {
      loadSessions()
    }
  }, [sessionsLoaded, loadSessions])

  // Refresh when navigating between pages
  useEffect(() => {
    loadSessions()
  }, [pathname, loadSessions])

  const handleNewSession = async () => {
    if (creating) return
    setCreating(true)
    try {
      const sessionId = await startNewSession()
      router.push(`/sessions/${sessionId}`)
    } catch (e) {
      console.error('Failed to create session:', e)
      alert(e instanceof Error ? e.message : 'Failed to create session')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (sessionId: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (deletingId) return
    if (!confirm(t('deleteSessionConfirm'))) return
    setDeletingId(sessionId)
    try {
      await removeSession(sessionId)
      if (pathname === `/sessions/${sessionId}`) {
        router.push('/')
      }
    } catch (err) {
      console.error('Failed to delete session:', err)
      alert(err instanceof Error ? err.message : 'Failed to delete session')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <aside className="w-[256px] h-screen flex flex-col bg-console-surface border-r border-console-border flex-shrink-0">
      {/* Product header */}
      <div className="h-14 px-4 border-b border-console-border flex items-center">
        <Link href="/" className="flex items-center min-w-0">
          <img
            src="/brand/webuild-wordmark.png"
            alt="WeBuild"
            width={128}
            height={28}
            className="h-7 w-auto object-contain"
          />
        </Link>
      </div>

      {/* New Session */}
      <div className="p-3">
        <button
          type="button"
          onClick={handleNewSession}
          disabled={creating}
          className="console-btn-primary w-full disabled:opacity-50"
        >
          {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          {t('newSession')}
        </button>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        <div className="flex items-center gap-1.5 px-2 py-2 text-[11px] font-medium text-console-faint uppercase tracking-wide">
          <Clock className="w-3 h-3" />
          {t('recent')}
        </div>
        {sessions.length === 0 ? (
          <div className="px-2 py-8 text-center">
            <MessageSquare className="w-7 h-7 text-console-border mx-auto mb-2" />
            <p className="text-xs text-console-faint">{t('noSessions')}</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {sessions.map((session) => (
              <div
                key={session.sessionId}
                className={`group flex items-center gap-0.5 rounded ${
                  pathname === `/sessions/${session.sessionId}`
                    ? 'bg-console-blue-soft'
                    : ''
                }`}
              >
                <Link
                  href={`/sessions/${session.sessionId}`}
                  className={`console-nav-item flex-1 min-w-0 ${
                    pathname === `/sessions/${session.sessionId}`
                      ? 'console-nav-item-active'
                      : ''
                  }`}
                >
                  <MessageSquare className="w-3.5 h-3.5 flex-shrink-0 opacity-60" />
                  <span className="truncate">
                    {session.title || session.sessionId.slice(0, 12)}
                  </span>
                </Link>
                <button
                  type="button"
                  title={t('deleteSession')}
                  onClick={(e) => handleDelete(session.sessionId, e)}
                  disabled={deletingId === session.sessionId}
                  className="p-1.5 mr-1 rounded opacity-0 group-hover:opacity-100 focus:opacity-100 text-console-faint hover:text-console-danger hover:bg-console-danger/10 transition-all disabled:opacity-50"
                >
                  {deletingId === session.sessionId ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="w-3.5 h-3.5" />
                  )}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-2 border-t border-console-border space-y-0.5">
        <div className="px-1 pb-1">
          <LocaleSwitcher compact />
        </div>
        <Link
          href="/sandboxes"
          className={`console-nav-item ${
            pathname?.startsWith('/sandboxes') ? 'console-nav-item-active' : ''
          }`}
        >
          <Box className="w-4 h-4" />
          Sandboxes
        </Link>
        <Link
          href="/settings"
          className={`console-nav-item ${
            pathname === '/settings' ? 'console-nav-item-active' : ''
          }`}
        >
          <Settings className="w-4 h-4" />
          {t('settings')}
        </Link>
        <div className="flex items-center gap-2 px-3 py-2">
          <span
            className={`w-2 h-2 rounded-full ${
              isConnected ? 'bg-console-success' : 'bg-console-danger'
            }`}
          />
          <span className="text-[11px] text-console-faint">
            {isConnected ? t('connected') : t('disconnected')}
          </span>
        </div>
      </div>
    </aside>
  )
}
