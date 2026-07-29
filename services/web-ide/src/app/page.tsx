'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Code2, Puzzle, Shield, Blocks, Loader2 } from 'lucide-react'
import { AppShell, NavMenuButton } from '@/components/app-shell'
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
    <AppShell>
      <main className="relative flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain bg-console-bg">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(26,115,232,0.07),_transparent_55%),linear-gradient(180deg,_#f8fafc_0%,_#f0f4f8_100%)]"
        />

        <header className="relative z-10 flex h-14 flex-shrink-0 items-center gap-2 border-b border-console-border bg-console-surface/90 px-3 backdrop-blur-sm sm:px-6">
          <NavMenuButton />
          <div className="text-sm text-console-muted">
            <span className="font-medium text-console-ink">{t('home')}</span>
          </div>
          <div className="ml-auto">
            <LocaleSwitcher />
          </div>
        </header>

        <div className="relative z-10 flex flex-1 flex-col items-center px-4 pb-10 pt-8 sm:px-6 sm:pt-14">
          <div className="mb-6 max-w-2xl animate-fade-in text-center sm:mb-7">
            <img
              src="/brand/webuild-wordmark.png"
              alt="WeBuild"
              width={220}
              height={55}
              className="mx-auto mb-4 h-10 w-auto object-contain sm:mb-5 sm:h-[55px]"
            />
            <h2 className="mb-2 text-[22px] font-normal tracking-tight text-console-ink sm:text-[26px]">
              {t('heroBefore')}
              <span className="font-medium text-console-blue">{t('heroHighlight')}</span>
              {t('heroAfter')}
            </h2>
            <p className="mx-auto max-w-xl text-sm leading-relaxed text-console-muted">
              {t('heroSubtitle')}
            </p>
          </div>

          <div className="mb-6 w-full max-w-2xl animate-fade-in sm:mb-8" style={{ animationDelay: '0.08s' }}>
            <div className="console-card p-1.5 shadow-console">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <input
                  type="text"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder={t('promptPlaceholder')}
                  disabled={starting}
                  className="min-w-0 flex-1 bg-transparent px-3.5 py-3 text-sm text-console-ink placeholder:text-console-faint focus:outline-none disabled:opacity-50"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                      startSession(e.currentTarget.value.trim())
                    }
                  }}
                />
                <button
                  onClick={() => startSession()}
                  disabled={starting}
                  className="console-btn-primary w-full flex-shrink-0 disabled:opacity-50 sm:w-auto"
                >
                  {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : t('start')}
                </button>
              </div>
            </div>
            <p className="mt-3 hidden text-center text-xs text-console-faint sm:block">
              {t('pressEnterHint')}{' '}
              <kbd className="rounded border border-console-border bg-console-surface px-1.5 py-0.5 text-[10px] text-console-muted">
                Enter
              </kbd>{' '}
              {t('toStartSession')}
            </p>
          </div>

          <div className="w-full max-w-2xl animate-fade-in" style={{ animationDelay: '0.16s' }}>
            <h3 className="mb-3 text-center text-xs font-medium uppercase tracking-wider text-console-faint">
              {t('capabilitiesHeading')}
            </h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {CAPABILITIES.map(({ icon: Icon, titleKey, descKey, promptKey, tone }) => (
                <button
                  key={titleKey}
                  onClick={() => startSession(t(promptKey))}
                  disabled={starting}
                  className="group console-card flex items-start gap-3 p-3.5 text-left transition-all hover:border-console-blue hover:shadow-console disabled:opacity-50"
                >
                  <span
                    className={`mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded ${tone}`}
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-console-ink transition-colors group-hover:text-console-blue-ink">
                      {t(titleKey)}
                    </span>
                    <span className="mt-1 block text-xs leading-snug text-console-muted">
                      {t(descKey)}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </main>
    </AppShell>
  )
}
