'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import {
  Plus, MessageSquare, Settings, Clock, Box, Loader2, Trash2, X
} from 'lucide-react'
import { useSessionStore } from '@/stores/session-store'
import { startNewSession } from '@/lib/start-session'
import { useI18n } from '@/lib/i18n'
import { LocaleSwitcher } from '@/components/locale-switcher'

type SidebarProps = {
  mobileOpen?: boolean
  onMobileClose?: () => void
}

export function Sidebar({ mobileOpen = false, onMobileClose }: SidebarProps) {
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

  useEffect(() => {
    loadSessions()
  }, [pathname, loadSessions])

  const handleNewSession = async () => {
    if (creating) return
    setCreating(true)
    try {
      const sessionId = await startNewSession()
      onMobileClose?.()
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
    <aside
      className={`
        fixed inset-y-0 left-0 z-50 flex h-[100dvh] w-[min(288px,85vw)] flex-col
        border-r border-console-border bg-console-surface
        transition-transform duration-200 ease-out
        md:static md:z-auto md:h-full md:w-[256px] md:translate-x-0 md:flex-shrink-0
        ${mobileOpen ? 'translate-x-0 shadow-console' : '-translate-x-full md:translate-x-0'}
      `}
    >
      {/* Product header */}
      <div className="flex h-14 flex-shrink-0 items-center gap-2 border-b border-console-border px-4">
        <Link href="/" className="flex min-w-0 items-center" onClick={onMobileClose}>
          <img
            src="/brand/webuild-wordmark.png"
            alt="WeBuild"
            width={128}
            height={28}
            className="h-7 w-auto object-contain"
          />
        </Link>
        <button
          type="button"
          onClick={onMobileClose}
          aria-label={t('closeMenu')}
          className="ml-auto inline-flex h-8 w-8 items-center justify-center rounded text-console-muted hover:bg-console-bg hover:text-console-ink md:hidden"
        >
          <X className="h-4 w-4" />
        </button>
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
      <div className="flex-1 overflow-y-auto overscroll-contain px-2 pb-2">
        <div className="flex items-center gap-1.5 px-2 py-2 text-[11px] font-medium uppercase tracking-wide text-console-faint">
          <Clock className="h-3 w-3" />
          {t('recent')}
        </div>
        {sessions.length === 0 ? (
          <div className="px-2 py-8 text-center">
            <MessageSquare className="mx-auto mb-2 h-7 w-7 text-console-border" />
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
                  onClick={onMobileClose}
                  className={`console-nav-item min-w-0 flex-1 ${
                    pathname === `/sessions/${session.sessionId}`
                      ? 'console-nav-item-active'
                      : ''
                  }`}
                >
                  <MessageSquare className="h-3.5 w-3.5 flex-shrink-0 opacity-60" />
                  <span className="truncate">
                    {session.title || session.sessionId.slice(0, 12)}
                  </span>
                </Link>
                <button
                  type="button"
                  title={t('deleteSession')}
                  onClick={(e) => handleDelete(session.sessionId, e)}
                  disabled={deletingId === session.sessionId}
                  className="mr-1 rounded p-1.5 text-console-faint opacity-100 transition-all hover:bg-console-danger/10 hover:text-console-danger focus:opacity-100 disabled:opacity-50 md:opacity-0 md:group-hover:opacity-100"
                >
                  {deletingId === session.sessionId ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="space-y-0.5 border-t border-console-border p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
        <div className="px-1 pb-1">
          <LocaleSwitcher compact />
        </div>
        <Link
          href="/sandboxes"
          onClick={onMobileClose}
          className={`console-nav-item ${
            pathname?.startsWith('/sandboxes') ? 'console-nav-item-active' : ''
          }`}
        >
          <Box className="h-4 w-4" />
          Sandboxes
        </Link>
        <Link
          href="/settings"
          onClick={onMobileClose}
          className={`console-nav-item ${
            pathname === '/settings' ? 'console-nav-item-active' : ''
          }`}
        >
          <Settings className="h-4 w-4" />
          {t('settings')}
        </Link>
        <div className="flex items-center gap-2 px-3 py-2">
          <span
            className={`h-2 w-2 rounded-full ${
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
