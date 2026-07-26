'use client'

import { useState } from 'react'
import { Sidebar } from '@/components/sidebar'
import { Server, Key, Save, Check, Wifi, WifiOff } from 'lucide-react'
import { useSessionStore } from '@/stores/session-store'

export default function SettingsPage() {
  const { isConnected } = useSessionStore()
  const [wsUrl, setWsUrl] = useState(
    typeof window !== 'undefined'
      ? localStorage.getItem('webuild_ws_url') || `ws://${window.location.host}/ws/relay`
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

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-8 py-10">
          <div className="animate-fade-in">
            <h1 className="text-2xl font-bold text-white mb-1">Settings</h1>
            <p className="text-gray-500 text-sm mb-8">Configure your WeBuild connection and preferences.</p>

            {/* Connection Status */}
            <div className="glass rounded-xl p-4 mb-6 flex items-center gap-3">
              {isConnected ? (
                <>
                  <Wifi className="w-5 h-5 text-emerald-400" />
                  <div>
                    <p className="text-sm text-white font-medium">Connected</p>
                    <p className="text-xs text-gray-500">Relay server is reachable</p>
                  </div>
                </>
              ) : (
                <>
                  <WifiOff className="w-5 h-5 text-red-400" />
                  <div>
                    <p className="text-sm text-white font-medium">Disconnected</p>
                    <p className="text-xs text-gray-500">Check your WebSocket URL and token</p>
                  </div>
                </>
              )}
            </div>

            {/* Relay Server */}
            <div className="bg-[#16213e]/60 rounded-xl border border-[#2a2a4a] p-6 mb-5">
              <div className="flex items-center gap-2.5 mb-5">
                <div className="w-8 h-8 rounded-lg bg-sky-600/20 flex items-center justify-center">
                  <Server className="w-4 h-4 text-sky-400" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-white">Relay Server</h2>
                  <p className="text-[11px] text-gray-500">WebSocket endpoint for ACP messages</p>
                </div>
              </div>
              <input
                type="text"
                value={wsUrl}
                onChange={(e) => setWsUrl(e.target.value)}
                placeholder="ws://localhost:8002/ws"
                className="w-full bg-[#0f0f23] border border-[#2a2a4a] rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 transition-all"
              />
            </div>

            {/* Authentication */}
            <div className="bg-[#16213e]/60 rounded-xl border border-[#2a2a4a] p-6 mb-8">
              <div className="flex items-center gap-2.5 mb-5">
                <div className="w-8 h-8 rounded-lg bg-emerald-600/20 flex items-center justify-center">
                  <Key className="w-4 h-4 text-emerald-400" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-white">Authentication</h2>
                  <p className="text-[11px] text-gray-500">JWT access token from the Auth Service</p>
                </div>
              </div>
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Paste your JWT token..."
                className="w-full bg-[#0f0f23] border border-[#2a2a4a] rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50 transition-all"
              />
            </div>

            {/* Save */}
            <button
              onClick={handleSave}
              className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-medium transition-all active:scale-[0.97] ${
                saved
                  ? 'bg-emerald-600 text-white'
                  : 'bg-indigo-600 hover:bg-indigo-500 text-white hover:shadow-lg hover:shadow-indigo-500/25'
              }`}
            >
              {saved ? <Check className="w-4 h-4" /> : <Save className="w-4 h-4" />}
              {saved ? 'Saved!' : 'Save Settings'}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
