'use client'

import { useState } from 'react'
import { Sidebar } from '@/components/sidebar'
import { Server, Key, Save, Check, Wifi, WifiOff } from 'lucide-react'
import { useSessionStore } from '@/stores/session-store'
import { useI18n } from '@/lib/i18n'
import { LocaleSwitcher } from '@/components/locale-switcher'

export default function SettingsPage() {
  const { isConnected } = useSessionStore()
  const { t } = useI18n()
  const [wsUrl, setWsUrl] = useState(
    typeof window !== 'undefined'
      ? localStorage.getItem('webuild_ws_url') || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/relay`
      : ''
  )
  const [token, setToken] = useState(
    typeof window !== 'undefined' ? localStorage.getItem('webuild_token') || '' : ''
  )
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    localStorage.setItem('webuild_ws_url', wsUrl)
    localStorage.setItem('webuild_token', token)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  return (
    <div className="flex h-screen">
      <Sidebar />

      <main className="flex-1 overflow-y-auto bg-console-bg">
        <header className="h-14 border-b border-console-border bg-console-surface flex items-center px-6 sticky top-0 z-10">
          <h1 className="text-sm font-medium text-console-ink">{t('settings')}</h1>
          <div className="ml-auto">
            <LocaleSwitcher />
          </div>
        </header>

        <div className="max-w-2xl mx-auto px-6 py-8">
          <div className="animate-fade-in">
            <h2 className="text-2xl font-normal text-console-ink mb-1">{t('settings')}</h2>
            <p className="text-console-muted text-sm mb-6">
              {t('settingsDesc')}
            </p>

            {/* Connection Status */}
            <div className="console-card p-4 mb-4 flex items-center gap-3">
              {isConnected ? (
                <>
                  <div className="w-9 h-9 rounded bg-console-success-soft flex items-center justify-center">
                    <Wifi className="w-4 h-4 text-console-success" />
                  </div>
                  <div>
                    <p className="text-sm text-console-ink font-medium">{t('connected')}</p>
                    <p className="text-xs text-console-faint">{t('relayReachable')}</p>
                  </div>
                </>
              ) : (
                <>
                  <div className="w-9 h-9 rounded bg-console-danger-soft flex items-center justify-center">
                    <WifiOff className="w-4 h-4 text-console-danger" />
                  </div>
                  <div>
                    <p className="text-sm text-console-ink font-medium">{t('disconnected')}</p>
                    <p className="text-xs text-console-faint">{t('checkWsToken')}</p>
                  </div>
                </>
              )}
            </div>

            {/* Relay Server */}
            <div className="console-card p-5 mb-4">
              <div className="flex items-center gap-2.5 mb-4">
                <div className="w-8 h-8 rounded bg-console-blue-soft flex items-center justify-center">
                  <Server className="w-4 h-4 text-console-blue" />
                </div>
                <div>
                  <h3 className="text-sm font-medium text-console-ink">{t('relayServer')}</h3>
                  <p className="text-[11px] text-console-faint">{t('relayDesc')}</p>
                </div>
              </div>
              <input
                type="text"
                value={wsUrl}
                onChange={(e) => setWsUrl(e.target.value)}
                placeholder="ws://localhost:8002/ws"
                className="console-input"
              />
            </div>

            {/* Authentication */}
            <div className="console-card p-5 mb-6">
              <div className="flex items-center gap-2.5 mb-4">
                <div className="w-8 h-8 rounded bg-console-success-soft flex items-center justify-center">
                  <Key className="w-4 h-4 text-console-success" />
                </div>
                <div>
                  <h3 className="text-sm font-medium text-console-ink">{t('authentication')}</h3>
                  <p className="text-[11px] text-console-faint">{t('authDesc')}</p>
                </div>
              </div>
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder={t('pasteToken')}
                className="console-input"
              />
            </div>

            {/* Save */}
            <button
              onClick={handleSave}
              className={`console-btn-primary ${
                saved ? '!bg-console-success hover:!bg-console-success' : ''
              }`}
            >
              {saved ? <Check className="w-4 h-4" /> : <Save className="w-4 h-4" />}
              {saved ? t('saved') : t('saveSettings')}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
