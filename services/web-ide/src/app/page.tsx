'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Code2, Puzzle, Shield, Blocks, Loader2 } from 'lucide-react'
import { Sidebar } from '@/components/sidebar'
import { startNewSession } from '@/lib/start-session'
import { useI18n, type MessageKey } from '@/lib/i18n'
import { LocaleSwitcher } from '@/components/locale-switcher'

const CAPABILITIES: {
  icon: typeof Code2
  titleKey: MessageKey
  descKey: MessageKey
  promptKey: MessageKey
  tone: string
}[] = [
  {
    icon: Code2,
    titleKey: 'capability1Title',
    descKey: 'capability1Desc',
    promptKey: 'capability1Prompt',
    tone: 'text-console-blue bg-console-blue-soft',
  },
  {
    icon: Puzzle,
    titleKey: 'capability2Title',
    descKey: 'capability2Desc',
    promptKey: 'capability2Prompt',
    tone: 'text-console-success bg-console-success-soft',
  },
  {
    icon: Shield,
    titleKey: 'capability3Title',
    descKey: 'capability3Desc',
    promptKey: 'capability3Prompt',
    tone: 'text-console-warn bg-console-warn-soft',
  },
  {
    icon: Blocks,
    titleKey: 'capability4Title',
    descKey: 'capability4Desc',
    promptKey: 'capability4Prompt',
    tone: 'text-console-blue-ink bg-console-blue-soft',
  },
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

      <main className="flex-1 flex flex-col overflow-y-auto relative bg-console-bg">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(26,115,232,0.07),_transparent_55%),linear-gradient(180deg,_#f8fafc_0%,_#f0f4f8_100%)]"
        />

        {/* Top bar */}
        <header className="relative z-10 h-14 border-b border-console-border bg-console-surface/90 backdrop-blur-sm flex items-center px-6 flex-shrink-0">
          <div className="text-sm text-console-muted">
            <span className="text-console-ink font-medium">{t('home')}</span>
          </div>
          <div className="ml-auto">
            <LocaleSwitcher />
          </div>
        </header>

        <div className="relative z-10 flex-1 flex flex-col items-center px-6 pt-14 pb-10">
          {/* Hero */}
          <div className="animate-fade-in text-center max-w-2xl mb-7">
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
            <p className="text-console-muted text-sm leading-relaxed max-w-xl mx-auto">
              {t('heroSubtitle')}
            </p>
          </div>

          {/* Quick Start Input */}
          <div className="w-full max-w-2xl mb-8 animate-fade-in" style={{ animationDelay: '0.08s' }}>
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
            <p className="mt-3 text-center text-xs text-console-faint">
              {t('pressEnterHint')}{' '}
              <kbd className="px-1.5 py-0.5 rounded border border-console-border bg-console-surface text-console-muted text-[10px]">
                Enter
              </kbd>{' '}
              {t('toStartSession')}
            </p>
          </div>

          {/* Core capabilities */}
          <div className="w-full max-w-2xl animate-fade-in" style={{ animationDelay: '0.16s' }}>
            <h3 className="text-xs font-medium uppercase tracking-wider text-console-faint mb-3 text-center">
              {t('capabilitiesHeading')}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {CAPABILITIES.map(({ icon: Icon, titleKey, descKey, promptKey, tone }) => (
                <button
                  key={titleKey}
                  onClick={() => startSession(t(promptKey))}
                  disabled={starting}
                  className="group flex items-start gap-3 p-3.5 text-left console-card hover:border-console-blue hover:shadow-console transition-all disabled:opacity-50"
                >
                  <span
                    className={`mt-0.5 w-8 h-8 rounded flex items-center justify-center flex-shrink-0 ${tone}`}
                  >
                    <Icon className="w-4 h-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-console-ink group-hover:text-console-blue-ink transition-colors">
                      {t(titleKey)}
                    </span>
                    <span className="block text-xs text-console-muted leading-snug mt-1">
                      {t(descKey)}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
