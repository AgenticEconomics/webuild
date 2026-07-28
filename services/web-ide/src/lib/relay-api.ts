const RELAY_BASE = typeof window !== 'undefined'
  ? `${window.location.protocol}//${window.location.host}/api/relay`
  : 'http://localhost:8002'

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('webuild_token') || '' : ''
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
}

export interface RelaySession {
  session_id: string
  user_id: string
  status: string
  title: string | null
  model: string | null
  browser_connected: boolean
  agent_connected: boolean
  created_at: string
  updated_at: string
}

export interface RelayHistoryMessage {
  id: number
  session_id: string
  seq: number
  direction: string
  method: string | null
  payload: Record<string, unknown>
  created_at: string | null
}

export async function listSessions(): Promise<RelaySession[]> {
  const res = await fetch(`${RELAY_BASE}/sessions`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.status}`)
  return res.json()
}

export async function createSession(opts?: {
  cwd?: string
  title?: string
  model?: string
}): Promise<RelaySession> {
  const res = await fetch(`${RELAY_BASE}/sessions`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({
      title: opts?.title ?? null,
      model: opts?.model ?? null,
    }),
  })
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`)
  return res.json()
}

export async function getSession(sessionId: string): Promise<RelaySession> {
  const res = await fetch(`${RELAY_BASE}/sessions/${sessionId}`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`Failed to get session: ${res.status}`)
  return res.json()
}

export async function updateSessionTitle(sessionId: string, title: string): Promise<void> {
  const res = await fetch(`${RELAY_BASE}/sessions/${sessionId}`, {
    method: 'PATCH',
    headers: getAuthHeaders(),
    body: JSON.stringify({ title }),
  })
  if (!res.ok) throw new Error(`Failed to update session: ${res.status}`)
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${RELAY_BASE}/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  })
  if (!res.ok) throw new Error(`Failed to delete session: ${res.status}`)
}

export async function getSessionHistory(
  sessionId: string,
  limit = 500,
): Promise<RelayHistoryMessage[]> {
  const res = await fetch(
    `${RELAY_BASE}/sessions/${sessionId}/history?limit=${limit}`,
    { headers: getAuthHeaders() },
  )
  if (!res.ok) throw new Error(`Failed to get history: ${res.status}`)
  return res.json()
}
