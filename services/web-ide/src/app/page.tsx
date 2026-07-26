'use client'

import { useRouter } from 'next/navigation'
import { Code2, Sparkles, Zap, Terminal, Globe } from 'lucide-react'
import { Sidebar } from '@/components/sidebar'

const SUGGESTIONS = [
  { icon: Zap, text: 'Help me debug this Rust async code', color: 'text-amber-400' },
  { icon: Terminal, text: 'Set up a Docker Compose for my project', color: 'text-emerald-400' },
  { icon: Globe, text: 'Create a REST API with FastAPI', color: 'text-sky-400' },
  { icon: Sparkles, text: 'Refactor this function for readability', color: 'text-purple-400' },
]

export default function DashboardPage() {
  const router = useRouter()

  const startSession = (prompt?: string) => {
    const sessionId = crypto.randomUUID()
    if (prompt) {
      sessionStorage.setItem(`initial_prompt_${sessionId}`, prompt)
    }
    router.push(`/sessions/${sessionId}`)
  }

  return (
    <div className="flex h-screen">
      <Sidebar />

      <main className="flex-1 flex flex-col items-center justify-center px-8 overflow-y-auto">
        {/* Hero */}
        <div className="animate-fade-in text-center max-w-xl mb-10">
          <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center shadow-2xl shadow-indigo-500/20">
            <Code2 className="w-8 h-8 text-white" />
          </div>
          <h2 className="text-3xl font-bold text-white mb-3">
            How can I help you <span className="text-gradient">code today</span>?
          </h2>
          <p className="text-gray-400 text-sm">
            Your AI programming assistant — write, debug, refactor, and deploy code with natural language.
          </p>
        </div>

        {/* Quick Start Input */}
        <div className="w-full max-w-2xl mb-8 animate-fade-in" style={{ animationDelay: '0.1s' }}>
          <div className="glass rounded-2xl p-1.5 shadow-xl shadow-black/20">
            <div className="flex items-center gap-3">
              <input
                type="text"
                placeholder="Describe what you want to build..."
                className="flex-1 bg-transparent px-4 py-3.5 text-sm text-white placeholder-gray-500 focus:outline-none"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                    startSession(e.currentTarget.value.trim())
                  }
                }}
              />
              <button
                onClick={() => startSession()}
                className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-xl transition-all hover:shadow-lg hover:shadow-indigo-500/25 active:scale-[0.97]"
              >
                Start
              </button>
            </div>
          </div>
        </div>

        {/* Suggestion Cards */}
        <div className="grid grid-cols-2 gap-3 w-full max-w-2xl animate-fade-in" style={{ animationDelay: '0.2s' }}>
          {SUGGESTIONS.map(({ icon: Icon, text, color }) => (
            <button
              key={text}
              onClick={() => startSession(text)}
              className="group flex items-center gap-3 p-4 rounded-xl bg-[#16213e]/60 hover:bg-[#1e1e3a] border border-[#2a2a4a] hover:border-indigo-500/30 transition-all text-left active:scale-[0.98]"
            >
              <Icon className={`w-5 h-5 ${color} flex-shrink-0 opacity-70 group-hover:opacity-100 transition-opacity`} />
              <span className="text-sm text-gray-300 group-hover:text-white transition-colors">{text}</span>
            </button>
          ))}
        </div>

        {/* Footer hint */}
        <p className="mt-10 text-[11px] text-gray-600 animate-fade-in" style={{ animationDelay: '0.3s' }}>
          Press <kbd className="px-1.5 py-0.5 rounded bg-[#1e1e3a] text-gray-400 text-[10px]">Enter</kbd> to start a session
        </p>
      </main>
    </div>
  )
}
