'use client'

import { useEffect, useCallback, useRef } from 'react'

const AUTH_BASE = typeof window !== 'undefined'
  ? `${window.location.protocol}//${window.location.host}/api/auth`
  : 'http://localhost:8001'

/**
 * Decode JWT payload without verification (just to read exp/iat).
 */
function decodeJwtPayload(token: string): { exp?: number; iat?: number; type?: string } | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = JSON.parse(atob(parts[1]))
    return payload
  } catch {
    return null
  }
}

/**
 * Refresh the access token using the refresh token.
 */
async function refreshAccessToken(refreshToken: string): Promise<string | null> {
  try {
    const res = await fetch(`${AUTH_BASE}/token/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return null
    const data = await res.json()
    return data.access_token || null
  } catch {
    return null
  }
}

/**
 * Hook that automatically refreshes the JWT access token before it expires.
 *
 * Stores:
 *   - `webuild_token` — current access token
 *   - `webuild_refresh_token` — refresh token (long-lived)
 *
 * Refresh happens 2 minutes before expiry. If refresh fails, the user
 * is NOT logged out — they'll just get auth errors on next API call.
 */
export function useTokenRefresh() {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const scheduleRefresh = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }

    const token = localStorage.getItem('webuild_token')
    const refreshToken = localStorage.getItem('webuild_refresh_token')

    if (!token || !refreshToken) return

    const payload = decodeJwtPayload(token)
    if (!payload?.exp) return

    const now = Math.floor(Date.now() / 1000)
    const expiresIn = payload.exp - now
    // Refresh 2 minutes before expiry, or in 5 seconds if already close
    const refreshIn = Math.max(expiresIn - 120, 5)

    if (refreshIn <= 0) {
      // Already expired or very close — refresh immediately
      doRefresh(refreshToken)
      return
    }

    timerRef.current = setTimeout(() => doRefresh(refreshToken), refreshIn * 1000)
  }, [])

  const doRefresh = useCallback(async (refreshToken: string) => {
    const newToken = await refreshAccessToken(refreshToken)
    if (newToken) {
      localStorage.setItem('webuild_token', newToken)
      console.log('[auth] Token refreshed successfully')
      // Schedule next refresh
      scheduleRefresh()
    } else {
      console.warn('[auth] Token refresh failed — user may need to re-login')
    }
  }, [scheduleRefresh])

  useEffect(() => {
    scheduleRefresh()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [scheduleRefresh])

  // Re-schedule when token changes (e.g., after manual login)
  useEffect(() => {
    const handler = () => scheduleRefresh()
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [scheduleRefresh])
}
