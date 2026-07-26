'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Key, Server, Save } from 'lucide-react'

export default function SettingsPage() {
  const router = useRouter()
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
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="min-h-screen bg-zinc-900 text-zinc-100">
      <div className="max-w-2xl mx-auto p-8">
        <button
          onClick={() => router.push('/')}
          className="flex items-center gap-2 text-zinc-400 hover:text-zinc-200 mb-8"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </button>

        <h1 className="text-2xl font-bold mb-8">Settings</h1>

        <div className="space-y-6">
          {/* WebSocket URL */}
          <div className="bg-zinc-800 rounded-lg border border-zinc-700 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Server className="w-5 h-5 text-blue-400" />
              <h2 className="text-lg font-semibold">Relay Server</h2>
            </div>
            <label className="block text-sm text-zinc-400 mb-2">WebSocket URL</label>
            <input
              type="text"
              value={wsUrl}
              onChange={(e) => setWsUrl(e.target.value)}
              placeholder="ws://localhost:8002/ws"
              className="w-full bg-zinc-900 border border-zinc-600 rounded-lg px-4 py-2 text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-zinc-500 mt-2">
              The WebSocket endpoint for the ACP relay server
            </p>
          </div>

          {/* Auth Token */}
          <div className="bg-zinc-800 rounded-lg border border-zinc-700 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Key className="w-5 h-5 text-green-400" />
              <h2 className="text-lg font-semibold">Authentication</h2>
            </div>
            <label className="block text-sm text-zinc-400 mb-2">API Token</label>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Your JWT or API key"
              className="w-full bg-zinc-900 border border-zinc-600 rounded-lg px-4 py-2 text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-zinc-500 mt-2">
              JWT access token from the Auth Service login endpoint
            </p>
          </div>

          {/* Save Button */}
          <button
            onClick={handleSave}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-medium transition-colors"
          >
            <Save className="w-4 h-4" />
            {saved ? 'Saved!' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  )
}
