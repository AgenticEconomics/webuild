import type { Message } from '@/stores/session-store'
import type { RelayHistoryMessage } from '@/lib/relay-api'

/**
 * Reconstruct chat bubbles from persisted ACP relay messages.
 * - User text from session/prompt (client → agent)
 * - Agent text from coalesced agent_message_chunk updates
 * - Skips user_message_chunk echoes and JSON-RPC result frames
 */
export function historyToMessages(rows: RelayHistoryMessage[]): Message[] {
  const messages: Message[] = []

  for (const row of rows) {
    const payload = row.payload || {}
    const method = row.method || (typeof payload.method === 'string' ? payload.method : null)

    if (method === 'session/prompt' && row.direction === 'client_to_agent') {
      const params = (payload.params || {}) as {
        prompt?: Array<{ type?: string; text?: string }>
      }
      const text = (params.prompt || [])
        .filter((b) => b?.type === 'text' && b.text)
        .map((b) => b.text as string)
        .join('')
      if (text) {
        messages.push({
          id: `hist-${row.id}`,
          role: 'user',
          content: text,
          timestamp: row.created_at ? Date.parse(row.created_at) : Date.now(),
        })
      }
      continue
    }

    if (method === 'session/update') {
      const params = (payload.params || {}) as {
        update?: {
          sessionUpdate?: string
          content?: { type?: string; text?: string }
        }
      }
      const update = params.update
      if (!update) continue

      // Skip echoed user chunks — already captured from session/prompt
      if (update.sessionUpdate === 'user_message_chunk') continue

      if (update.sessionUpdate === 'agent_message_chunk') {
        const text = update.content?.text || ''
        if (!text) continue
        const last = messages[messages.length - 1]
        if (last?.role === 'agent') {
          last.content += text
        } else {
          messages.push({
            id: `hist-${row.id}`,
            role: 'agent',
            content: text,
            timestamp: row.created_at ? Date.parse(row.created_at) : Date.now(),
          })
        }
      }
    }
  }

  return messages
}
