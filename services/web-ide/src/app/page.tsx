'use client'

import { useRouter } from 'next/navigation'
import { Plus, Terminal, Code2 } from 'lucide-react'
import { useSessionStore } from '@/stores/session-store'
import { useEffect } from 'react'

export default function DashboardPage() {
  const router = useRouter()
  const { sessions, activeSessionId, createSession, isConnected } = useSessionStore()

  const handleNewSession = async () => {
    try {
      const sessionId = await createSession('/workspace')
      router.push(`/sessions/${sessionId}`)
    } catch (e) {
      console.error('Failed to create session:', e)
    }
  }

  return (
    <div className="flex h-screen bg-zinc-900 text-zinc-100">
      {/* Main content */}
      <main className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="max-w-2xl w-full space-y-8">
          <div className="text-center space-y-2">
            <h2 className="text-3xl font-bold text-zinc-100 flex items-center justify-center gap-3">
              <Code2 className="w-8 h-8 text-blue-400" />
              WeBuild Web IDE
            </h2>
            <p className="text-zinc-400">
              AI-powered programming assistant for your development workflow
            </p>
            {isConnected && (
              <span className="inline-flex items-center gap-1 text-xs text-green-400">
                <span className="w-2 h-2 rounded-full bg-green-500" />
                Connected
              </span>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <button
              onClick={handleNewSession}
              className="flex items-center gap-3 p-6 bg-zinc-800 hover:bg-zinc-700 rounded-lg border border-zinc-700 transition-colors"
            >
              <Plus className="w-8 h-8 text-blue-400" />
              <div className="text-left">
                <h3 className="text-lg font-semibold text-zinc-100">New Session</h3>
                <p className="text-sm text-zinc-400">
                  Start a new AI programming session
                </p>
              </div>
            </button>

            <button
              onClick={() => router.push('/settings')}
              className="flex items-center gap-3 p-6 bg-zinc-800 hover:bg-zinc-700 rounded-lg border border-zinc-700 transition-colors"
            >
              <Terminal className="w-8 h-8 text-green-400" />
              <div className="text-left">
                <h3 className="text-lg font-semibold text-zinc-100">Settings</h3>
                <p className="text-sm text-zinc-400">
                  Configure API keys and preferences
                </p>
              </div>
            </button>
          </div>

          {sessions.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-zinc-400 uppercase">
                Recent Sessions
              </h3>
              <div className="space-y-1">
                {sessions.slice(0, 5).map((session) => (
                  <button
                    key={session.sessionId}
                    onClick={() => router.push(`/sessions/${session.sessionId}`)}
                    className={`w-full text-left p-3 rounded border transition-colors ${
                      session.sessionId === activeSessionId
                        ? 'bg-zinc-700 border-blue-500'
                        : 'bg-zinc-800 hover:bg-zinc-700 border-zinc-700'
                    }`}
                  >
                    <div className="font-medium text-zinc-100">
                      {session.title || session.sessionId.slice(0, 16)}
                    </div>
                    <div className="text-xs text-zinc-400">
                      {session.status}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
