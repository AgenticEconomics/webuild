'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Sparkles, Zap, Terminal, Globe, Loader2 } from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import { startNewSession } from '@/lib/start-session'
import { useI18n, type MessageKey } from '@/lib/i18n'
import { LocaleSwitcher } from '@/components/locale-switcher'

const SUGGESTIONS: { icon: typeof Zap; key: MessageKey; tone: string }[] = [
  { icon: Zap, key: 'suggestion1', tone: 'text-console-warn bg-console-warn-soft' },
  { icon: Terminal, key: 'suggestion2', tone: 'text-console-success bg-console-success-soft' },
  { icon: Globe, key: 'suggestion3', tone: 'text-console-blue bg-console-blue-soft' },
  { icon: Sparkles, key: 'suggestion4', tone: 'text-console-blue-ink bg-console-blue-soft' },
]

export default function DashboardPage() {
  const router = useRouter()
  const { t } = useI18n()
  const [starting, setStarting] = useState(false)
  const [prompt, setPrompt] = useState('')

  const startSession = async (initialPrompt?: string) => {
    if (starting) return
    setStarting(true)
    try {
      const text = (initialPrompt || prompt).trim()
      const sessionId = await startNewSession(text ? text.slice(0, 48) : undefined)
      if (text) {
        sessionStorage.setItem(`initial_prompt_${sessionId}`, text)
      }
      router.push(`/sessions/${sessionId}`)
    } catch (e) {
      console.error('Failed to start session:', e)
      alert(e instanceof Error ? e.message : 'Failed to start session')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="flex h-screen">
      <Sidebar />

      <main className="flex-1 flex flex-col overflow-y-auto bg-console-bg">
        {/* Top bar */}
        <header className="h-14 border-b border-console-border bg-console-surface flex items-center px-6 flex-shrink-0">
          <div className="text-sm text-console-muted">
            <span className="text-console-ink font-medium">{t('home')}</span>
          </div>
          <div className="ml-auto">
            <LocaleSwitcher />
          </div>
        </header>

        <div className="flex-1 flex flex-col items-center px-6 pt-16 pb-10">
          {/* Hero */}
          <div className="animate-fade-in text-center max-w-xl mb-7">
            <img
              src="/brand/webuild-wordmark.png"
              alt="WeBuild"
              width={220}
              height={55}
              className="h-[55px] w-auto mx-auto mb-5 object-contain"
            />
            <h2 className="text-[26px] font-normal text-console-ink tracking-tight mb-2">
              {t('heroBefore')}
              <span className="text-console-blue font-medium">{t('heroHighlight')}</span>
              {t('heroAfter')}
            </h2>
            <p className="text-console-muted text-sm leading-relaxed">
              {t('heroSubtitle')}
            </p>
          </div>

          {/* Quick Start Input */}
          <div className="w-full max-w-2xl mb-5 animate-fade-in" style={{ animationDelay: '0.08s' }}>
            <div className="console-card shadow-console p-1.5">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder={t('promptPlaceholder')}
                  disabled={starting}
                  className="flex-1 bg-transparent px-3.5 py-3 text-sm text-console-ink placeholder:text-console-faint focus:outline-none disabled:opacity-50"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                      startSession(e.currentTarget.value.trim())
                    }
                  }}
                />
                <button
                  onClick={() => startSession()}
                  disabled={starting}
                  className="console-btn-primary flex-shrink-0 disabled:opacity-50"
                >
                  {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : t('start')}
                </button>
              </div>
            </div>
          </div>

          {/* Suggestion Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl animate-fade-in" style={{ animationDelay: '0.16s' }}>
            {SUGGESTIONS.map(({ icon: Icon, key, tone }) => {
              const text = t(key)
              return (
                <button
                  key={key}
                  onClick={() => startSession(text)}
                  disabled={starting}
                  className="group flex items-start gap-3 p-3.5 text-left console-card hover:border-console-blue hover:shadow-console transition-all disabled:opacity-50"
                >
                  <span className={`mt-0.5 w-8 h-8 rounded flex items-center justify-center flex-shrink-0 ${tone}`}>
                    <Icon className="w-4 h-4" />
                  </span>
                  <span className="text-sm text-console-ink leading-snug group-hover:text-console-blue-ink transition-colors">
                    {text}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Footer hint */}
          <p className="mt-6 text-xs text-console-faint animate-fade-in" style={{ animationDelay: '0.24s' }}>
            {t('pressEnterHint')}{' '}
            <kbd className="px-1.5 py-0.5 rounded border border-console-border bg-console-surface text-console-muted text-[10px]">
              Enter
            </kbd>{' '}
            {t('toStartSession')}
          </p>
        </div>
      </main>
    </div>
  )
}
