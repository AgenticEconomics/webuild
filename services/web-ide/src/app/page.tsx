'use client'

import { useRouter } from 'next/navigation'
import { Plus, Terminal, Code2 } from 'lucide-react'
import { useSessionStore } from '@/stores/session-store'
import { SessionList } from '@/components/session-list'
import { useEffect } from 'react'

export default function DashboardPage() {
  const router = useRouter()
  const { connect, sessions } = useSessionStore()

  useEffect(() => {
    connect()
  }, [connect])

  const handleNewSession = async () => {
    const sessionId = crypto.randomUUID()
    router.push(`/sessions/${sessionId}`)
  }

  const handleNewSandbox = async () => {
    const sandboxId = crypto.randomUUID()
    router.push(`/sandboxes/${sandboxId}`)
  }

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-64 border-r border-gray-800 bg-gray-950 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Code2 className="w-6 h-6" />
            WeBuild
          </h1>
        </div>
        <SessionList sessions={sessions} />
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="max-w-2xl w-full space-y-8">
          <div className="text-center space-y-2">
            <h2 className="text-3xl font-bold text-white">
              Welcome to WeBuild Web IDE
            </h2>
            <p className="text-gray-400">
              AI-powered programming assistant for your development workflow
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <button
              onClick={handleNewSession}
              className="flex items-center gap-3 p-6 bg-gray-800 hover:bg-gray-700 rounded-lg border border-gray-700 transition-colors"
            >
              <Plus className="w-8 h-8 text-blue-400" />
              <div className="text-left">
                <h3 className="text-lg font-semibold text-white">New Session</h3>
                <p className="text-sm text-gray-400">
                  Start a new AI programming session
                </p>
              </div>
            </button>

            <button
              onClick={handleNewSandbox}
              className="flex items-center gap-3 p-6 bg-gray-800 hover:bg-gray-700 rounded-lg border border-gray-700 transition-colors"
            >
              <Terminal className="w-8 h-8 text-green-400" />
              <div className="text-left">
                <h3 className="text-lg font-semibold text-white">New Sandbox</h3>
                <p className="text-sm text-gray-400">
                  Create an isolated development environment
                </p>
              </div>
            </button>
          </div>

          {sessions.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-400 uppercase">
                Recent Sessions
              </h3>
              <div className="space-y-1">
                {sessions.slice(0, 5).map((session) => (
                  <button
                    key={session.id}
                    onClick={() => router.push(`/sessions/${session.id}`)}
                    className="w-full text-left p-3 bg-gray-800 hover:bg-gray-700 rounded border border-gray-700 transition-colors"
                  >
                    <div className="font-medium text-white">
                      {session.title || 'Untitled Session'}
                    </div>
                    <div className="text-xs text-gray-400">
                      {new Date(session.createdAt).toLocaleString()}
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
