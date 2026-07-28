const GATEWAY_BASE = typeof window !== 'undefined'
  ? `${window.location.protocol}//${window.location.host}/api/gateway`
  : 'http://localhost:8004'

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('webuild_token') || '' : ''
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
}

export interface Sandbox {
  id: string
  user_id: string
  environment_id: string
  status: 'creating' | 'running' | 'terminated'
  pod_name: string
  namespace: string
  created_at: string
  expires_at: string
  terminated_at: string | null
  pod_phase?: string | null
}

export interface SandboxEnvironment {
  id: string
  name: string
  container_image: string
  resource_profile: {
    cpu_request: string
    memory_request: string
    cpu_limit: string
    memory_limit: string
  }
  max_ttl_seconds: number
}

export async function listEnvironments(): Promise<SandboxEnvironment[]> {
  const res = await fetch(`${GATEWAY_BASE}/environments`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`Failed to list environments: ${res.status}`)
  return res.json()
}

export async function listSandboxes(): Promise<Sandbox[]> {
  const res = await fetch(`${GATEWAY_BASE}/sandboxes`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`Failed to list sandboxes: ${res.status}`)
  const data = await res.json()
  return data.sandboxes || data || []
}

export async function createSandbox(environmentId = 'default', sandboxId?: string): Promise<Sandbox> {
  const body: Record<string, string> = { environment_id: environmentId }
  if (sandboxId) body.id = sandboxId
  const res = await fetch(`${GATEWAY_BASE}/sandboxes`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`Failed to create sandbox: ${res.status}${detail ? ` ${detail}` : ''}`)
  }
  return res.json()
}

export async function getSandboxLogs(id: string, tailLines = 200): Promise<string> {
  const res = await fetch(
    `${GATEWAY_BASE}/sandboxes/${id}/logs?tail_lines=${tailLines}`,
    { headers: getAuthHeaders() },
  )
  if (!res.ok) throw new Error(`Failed to get logs: ${res.status}`)
  // Gateway returns PlainTextResponse
  return res.text()
}

export async function getSandbox(id: string): Promise<Sandbox> {
  const res = await fetch(`${GATEWAY_BASE}/sandboxes/${id}`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`Failed to get sandbox: ${res.status}`)
  return res.json()
}

export async function terminateSandbox(id: string): Promise<void> {
  const res = await fetch(`${GATEWAY_BASE}/sandboxes/${id}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  })
  if (!res.ok) throw new Error(`Failed to terminate sandbox: ${res.status}`)
}
