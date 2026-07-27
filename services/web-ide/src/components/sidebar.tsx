'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Plus, MessageSquare, Settings, Clock
} from 'lucide-react'
import { useSessionStore } from '@/stores/session-store'
import { generateId } from '@/lib/uuid'
import { useI18n } from '@/lib/i18n'
import { LocaleSwitcher } from '@/components/locale-switcher'

export function Sidebar() {
  const pathname = usePathname()
  const { sessions, isConnected } = useSessionStore()
  const { t } = useI18n()

  return (
    <aside className="w-[256px] h-screen flex flex-col bg-console-surface border-r border-console-border flex-shrink-0">
      {/* Product header */}
      <div className="h-14 px-4 border-b border-console-border flex items-center">
        <Link href="/" className="flex items-center gap-2.5 group min-w-0">
          <img
            src="/brand/webuild-mark.png"
            alt="WeBuild"
            width={32}
            height={32}
            className="w-8 h-8 rounded flex-shrink-0 object-cover ring-1 ring-console-border"
          />
          <div className="min-w-0">
            <h1 className="text-sm font-medium text-console-ink leading-tight group-hover:text-console-blue transition-colors">
              WeBuild
            </h1>
            <p className="text-[11px] text-console-faint leading-tight truncate">
              {t('tagline')}
            </p>
          </div>
        </Link>
      </div>

      {/* New Session */}
      <div className="p-3">
        <Link
          href={`/sessions/${generateId()}`}
          className="console-btn-primary w-full"
        >
          <Plus className="w-4 h-4" />
          {t('newSession')}
        </Link>
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
              <Link
                key={session.sessionId}
                href={`/sessions/${session.sessionId}`}
                className={`console-nav-item ${
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
