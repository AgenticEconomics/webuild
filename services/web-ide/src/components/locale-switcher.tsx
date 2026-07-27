'use client'

import { useI18n, type Locale } from '@/lib/i18n'

export function LocaleSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n()

  const options: { value: Locale; label: string }[] = [
    { value: 'en', label: t('langEn') },
    { value: 'zh', label: t('langZh') },
  ]

  return (
    <div
      className={`inline-flex items-center rounded border border-console-border bg-console-surface p-0.5 ${
        compact ? '' : 'gap-0'
      }`}
      role="group"
      aria-label={t('language')}
    >
      {options.map(({ value, label }) => {
        const active = locale === value
        return (
          <button
            key={value}
            type="button"
            onClick={() => setLocale(value)}
            className={`px-2 py-1 text-[11px] font-medium rounded-sm transition-colors ${
              active
                ? 'bg-console-blue-soft text-console-blue-ink'
                : 'text-console-faint hover:text-console-ink hover:bg-console-bg'
            }`}
            aria-pressed={active}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
