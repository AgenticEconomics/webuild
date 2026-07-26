'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Plus, MessageSquare, Settings, Code2, ChevronLeft,
  Sparkles, Clock
} from 'lucide-react'
import { useSessionStore } from '@/stores/session-store'

export function Sidebar() {
  const pathname = usePathname()
  const { sessions, isConnected } = useSessionStore()

  return (
    <aside className="w-[260px] h-screen flex flex-col bg-[#0f0f23] border-r border-[#2a2a4a] flex-shrink-0">
      {/* Logo */}
      <div className="p-5 border-b border-[#2a2a4a]">
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Code2 className="w-4.5 h-4.5 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white group-hover:text-indigo-300 transition-colors">
              WeBuild
            </h1>
            <p className="text-[10px] text-gray-500">AI Programming Assistant</p>
          </div>
        </Link>
      </div>

      {/* New Session */}
      <div className="p-3">
        <Link
          href={`/sessions/${crypto.randomUUID()}`}
          className="flex items-center gap-2.5 w-full px-3.5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-all hover:shadow-lg hover:shadow-indigo-500/20 active:scale-[0.98]"
        >
          <Plus className="w-4 h-4" />
          New Session
        </Link>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto px-3 pb-3">
        <div className="flex items-center gap-1.5 px-2 py-2 text-[11px] font-medium text-gray-500 uppercase tracking-wider">
          <Clock className="w-3 h-3" />
          Recent
        </div>
        {sessions.length === 0 ? (
          <div className="px-2 py-6 text-center">
            <MessageSquare className="w-8 h-8 text-gray-700 mx-auto mb-2" />
            <p className="text-xs text-gray-600">No sessions yet</p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {sessions.map((session) => (
              <Link
                key={session.sessionId}
                href={`/sessions/${session.sessionId}`}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all ${
                  pathname === `/sessions/${session.sessionId}`
                    ? 'bg-[#1e1e3a] text-white'
                    : 'text-gray-400 hover:bg-[#1a1a30] hover:text-gray-200'
                }`}
              >
                <MessageSquare className="w-3.5 h-3.5 flex-shrink-0 opacity-50" />
                <span className="truncate">
                  {session.title || session.sessionId.slice(0, 12)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-[#2a2a4a] space-y-1">
        <Link
          href="/settings"
          className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all ${
            pathname === '/settings'
              ? 'bg-[#1e1e3a] text-white'
              : 'text-gray-400 hover:bg-[#1a1a30] hover:text-gray-200'
          }`}
        >
          <Settings className="w-4 h-4" />
          Settings
        </Link>
        <div className="flex items-center gap-2 px-3 py-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-red-400'}`} />
          <span className="text-[11px] text-gray-500">
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>
    </aside>
  )
}
