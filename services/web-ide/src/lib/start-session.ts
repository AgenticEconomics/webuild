import { createSession } from '@/lib/relay-api'
import { createSandbox } from '@/lib/gateway-api'
import { useSessionStore } from '@/stores/session-store'

/**
 * Create a relay session and provision a linked sandbox (same id).
 * Sandbox is best-effort: if gateway is unavailable, the lightweight
 * agent service can still join via /discover.
 */
export async function startNewSession(title?: string): Promise<string> {
  const session = await createSession({ title })
  const sessionId = session.session_id

  useSessionStore.getState().upsertSession({
    sessionId,
    title: session.title || title || undefined,
    status: session.status || 'created',
    sandboxId: sessionId,
  })

  // Link: sandbox id === session id so sandbox agent joins this session
  try {
    await createSandbox('default', sessionId)
  } catch (e) {
    console.warn('Sandbox provision skipped (gateway may be offline):', e)
  }

  return sessionId
}
