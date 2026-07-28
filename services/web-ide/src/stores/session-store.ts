import { create } from "zustand";
import { AcpClient } from "@/lib/acp-client";
import {
  listSessions as listRelaySessions,
  getSession,
  getSessionHistory,
  deleteSession as deleteRelaySession,
  updateSessionTitle,
} from "@/lib/relay-api";
import { historyToMessages } from "@/lib/session-history";

export interface Message {
  id: string;
  role: "user" | "agent" | "thought";
  content: string;
  timestamp: number;
}

export interface ToolCall {
  toolCallId: string;
  title: string;
  kind: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  rawInput?: unknown;
  rawOutput?: unknown;
}

export interface SessionInfo {
  sessionId: string;
  title?: string;
  status: string;
  /** Linked sandbox id (same as sessionId when provisioned together) */
  sandboxId?: string;
}

interface SessionState {
  client: AcpClient | null;
  isConnected: boolean;
  /** Session id the current WebSocket is actually paired with on the relay */
  connectedSessionId: string | null;
  /** ACP initialize + session/new completed for connectedSessionId */
  acpReady: boolean;
  agentConnected: boolean;
  sessions: SessionInfo[];
  activeSessionId: string | null;
  messages: Message[];
  toolCalls: ToolCall[];
  sessionsLoaded: boolean;
  historyLoading: boolean;

  connect: (wsUrl: string, token: string, sessionId: string) => Promise<void>;
  disconnect: () => void;
  createSession: (cwd: string) => Promise<string>;
  sendMessage: (text: string) => Promise<void>;
  cancelCurrent: () => void;
  approvePermission: (requestId: number, optionId: string) => void;
  rejectPermission: (requestId: number) => void;
  loadSessions: () => Promise<void>;
  loadHistory: (sessionId: string) => Promise<void>;
  removeSession: (sessionId: string) => Promise<void>;
  upsertSession: (session: SessionInfo) => void;
  setActiveSession: (sessionId: string) => void;
}

let msgCounter = 0;
/** Serialize connect() so React Strict Mode / rapid nav don't open duplicate sockets */
let connectEpoch = 0;
/** Ignore stale history responses when switching sessions quickly */
let historyEpoch = 0;

const AGENT_WAIT_MS = 120_000;
const AGENT_POLL_MS = 2_000;

async function waitForAgentConnected(
  sessionId: string,
  epoch: number,
  isStale: () => boolean,
): Promise<boolean> {
  const deadline = Date.now() + AGENT_WAIT_MS;
  while (Date.now() < deadline) {
    if (isStale() || epoch !== connectEpoch) return false;
    try {
      const s = await getSession(sessionId);
      if (s.agent_connected) return true;
    } catch {
      // Relay may briefly 404 while session is creating
    }
    await new Promise((r) => setTimeout(r, AGENT_POLL_MS));
  }
  return false;
}

function defaultWsUrl(): string {
  if (typeof window === "undefined") return "";
  const stored = localStorage.getItem("webuild_ws_url");
  if (stored) return stored;
  const host = window.location.hostname;
  const port = window.location.port;
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  // Local docker-compose exposes relay on :8002 (nginx profile is off)
  if (port === "3000" || port === "3001") {
    return `${wsProtocol}//${host}:8002/ws`;
  }
  return `${wsProtocol}//${host}/ws/relay`;
}

export const useSessionStore = create<SessionState>((set, get) => ({
  client: null,
  isConnected: false,
  connectedSessionId: null,
  acpReady: false,
  agentConnected: false,
  sessions: [],
  activeSessionId: null,
  messages: [],
  toolCalls: [],
  sessionsLoaded: false,
  historyLoading: false,

  connect: async (wsUrl, token, sessionId) => {
    if (!sessionId) throw new Error("sessionId is required");

    // Already paired with this session — keep existing socket
    if (
      get().isConnected &&
      get().connectedSessionId === sessionId &&
      get().client
    ) {
      set({ activeSessionId: sessionId });
      return;
    }

    const epoch = ++connectEpoch;
    const existing = get().client;
    if (existing) {
      existing.disconnect();
      set({
        client: null,
        isConnected: false,
        connectedSessionId: null,
        acpReady: false,
        agentConnected: false,
      });
    }

    const client = new AcpClient();

    client.onSessionUpdate((updateSessionId, update) => {
      if (updateSessionId !== get().activeSessionId) return;

      switch (update.sessionUpdate) {
        case "user_message_chunk": {
          // User message already added optimistically in sendMessage — ignore echo
          break;
        }
        case "agent_message_chunk": {
          const text = (update.content as { text?: string })?.text || "";
          if (!text) break;
          set((s) => {
            const last = s.messages[s.messages.length - 1];
            if (last?.role === "agent") {
              return {
                messages: [
                  ...s.messages.slice(0, -1),
                  { ...last, content: last.content + text },
                ],
              };
            }
            return {
              messages: [
                ...s.messages,
                { id: `msg-${++msgCounter}`, role: "agent", content: text, timestamp: Date.now() },
              ],
            };
          });
          break;
        }
        case "tool_call":
        case "tool_call_update": {
          const tc: ToolCall = {
            toolCallId: update.toolCallId || "",
            title: (update.title as string) || "Tool call",
            kind: (update.kind as string) || "other",
            status: (update.status as ToolCall["status"]) || "pending",
            rawInput: update.rawInput,
            rawOutput: update.rawOutput,
          };
          set((s) => {
            const idx = s.toolCalls.findIndex((t) => t.toolCallId === tc.toolCallId);
            if (idx >= 0) {
              const updated = [...s.toolCalls];
              updated[idx] = { ...updated[idx], ...tc };
              return { toolCalls: updated };
            }
            return { toolCalls: [...s.toolCalls, tc] };
          });
          break;
        }
      }
    });

    client.onDisconnect(() => {
      if (get().client === client) {
        set({
          isConnected: false,
          connectedSessionId: null,
          acpReady: false,
          agentConnected: false,
        });
      }
    });

    // Sandbox YOLO: auto-approve any leftover permission prompts so tools
    // never hang if the agent still asks the client.
    client.onPermissionRequest((req) => {
      const allow =
        req.options.find((o) => /allow|approve|yes|once/i.test(o.optionId) || /allow|approve/i.test(o.name))
        ?? req.options[0];
      if (allow) {
        client.respondPermission(req.id, allow.optionId);
      } else {
        client.rejectPermission(req.id);
      }
    });

    await client.connect(wsUrl || defaultWsUrl(), token, sessionId);

    if (epoch !== connectEpoch) {
      client.disconnect();
      return;
    }

    set({
      client,
      isConnected: true,
      connectedSessionId: sessionId,
      activeSessionId: sessionId,
      acpReady: false,
      agentConnected: false,
    });
    get().upsertSession({
      sessionId,
      status: "active",
      sandboxId: sessionId,
    });

    // Wait for ACS sandbox agent, then run ACP initialize + session/new
    const agentOk = await waitForAgentConnected(
      sessionId,
      epoch,
      () => get().client !== client,
    );
    if (epoch !== connectEpoch || get().client !== client) return;

    set({ agentConnected: agentOk });
    if (!agentOk) {
      console.warn("Agent not connected within timeout; ACP handshake deferred");
      return;
    }

    try {
      await client.ensureAcpSession("/workspace", sessionId);
      if (epoch !== connectEpoch || get().client !== client) return;
      set({ acpReady: true });
    } catch (e) {
      console.error("ACP handshake failed:", e);
      set({ acpReady: false });
    }
  },

  disconnect: () => {
    connectEpoch++;
    get().client?.disconnect();
    set({
      client: null,
      isConnected: false,
      connectedSessionId: null,
      acpReady: false,
      agentConnected: false,
    });
  },

  createSession: async (cwd) => {
    const { client } = get();
    if (!client) throw new Error("Not connected");
    const { sessionId } = await client.newSession(cwd);
    set((s) => ({
      activeSessionId: sessionId,
      acpReady: true,
      sessions: s.sessions.some((x) => x.sessionId === sessionId)
        ? s.sessions
        : [...s.sessions, { sessionId, status: "active", sandboxId: sessionId }],
      messages: [],
      toolCalls: [],
    }));
    return sessionId;
  },

  sendMessage: async (text) => {
    const { client, activeSessionId, connectedSessionId, isConnected, acpReady, agentConnected } =
      get();
    if (!client || !activeSessionId) {
      throw new Error("Not connected to a session");
    }
    if (!isConnected || connectedSessionId !== activeSessionId) {
      throw new Error("WebSocket is not paired with this session yet — wait for Connected");
    }
    if (!agentConnected) {
      // One more poll in case agent just came up
      try {
        const s = await getSession(activeSessionId);
        if (!s.agent_connected) {
          throw new Error("Sandbox agent is not connected yet — wait until status is Running");
        }
        set({ agentConnected: true });
      } catch (e) {
        if (e instanceof Error && e.message.includes("Sandbox agent")) throw e;
        throw new Error("Sandbox agent is not connected yet — wait until status is Running");
      }
    }
    if (!acpReady && !client.isAcpReady()) {
      await client.ensureAcpSession("/workspace", activeSessionId);
      set({ acpReady: true });
    }

    const needsTitle = !get().sessions.find((s) => s.sessionId === activeSessionId)?.title;

    set((s) => ({
      messages: [
        ...s.messages,
        { id: `msg-${++msgCounter}`, role: "user", content: text, timestamp: Date.now() },
      ],
      sessions: s.sessions.map((sess) =>
        sess.sessionId === activeSessionId && !sess.title
          ? { ...sess, title: text.slice(0, 48) }
          : sess
      ),
    }));

    if (needsTitle) {
      updateSessionTitle(activeSessionId, text.slice(0, 48)).catch(() => {});
    }

    await client.prompt(activeSessionId, text);
  },

  cancelCurrent: () => {
    const { client, activeSessionId } = get();
    if (client && activeSessionId) client.cancel(activeSessionId);
  },

  approvePermission: (requestId, optionId) => {
    get().client?.respondPermission(requestId, optionId);
  },

  rejectPermission: (requestId) => {
    get().client?.rejectPermission(requestId);
  },

  loadSessions: async () => {
    try {
      const remote = await listRelaySessions();
      const mapped: SessionInfo[] = remote.map((s) => ({
        sessionId: s.session_id,
        title: s.title || undefined,
        status: s.status,
        sandboxId: s.session_id,
      }));
      set((state) => {
        const byId = new Map<string, SessionInfo>();
        for (const s of mapped) byId.set(s.sessionId, s);
        for (const s of state.sessions) {
          const existing = byId.get(s.sessionId);
          if (!existing) byId.set(s.sessionId, s);
          else if (!existing.title && s.title) byId.set(s.sessionId, { ...existing, title: s.title });
        }
        return {
          sessions: Array.from(byId.values()),
          sessionsLoaded: true,
        };
      });
    } catch (e) {
      console.warn("Failed to load sessions from relay:", e);
      set({ sessionsLoaded: true });
    }
  },

  loadHistory: async (sessionId) => {
    const epoch = ++historyEpoch;
    set({ historyLoading: true });
    try {
      const rows = await getSessionHistory(sessionId);
      if (epoch !== historyEpoch || get().activeSessionId !== sessionId) return;
      const messages = historyToMessages(rows);
      set((s) => {
        if (s.activeSessionId !== sessionId) return { historyLoading: false };
        // Don't wipe messages the user already sent while history was loading
        if (s.messages.some((m) => m.id.startsWith("msg-"))) {
          return { historyLoading: false };
        }
        return { messages, toolCalls: [], historyLoading: false };
      });
    } catch (e) {
      console.warn("Failed to load session history:", e);
      if (epoch === historyEpoch && get().activeSessionId === sessionId) {
        set({ historyLoading: false });
      }
    }
  },

  removeSession: async (sessionId) => {
    await deleteRelaySession(sessionId);
    const state = get();
    if (state.activeSessionId === sessionId) {
      state.disconnect();
      set({
        activeSessionId: null,
        messages: [],
        toolCalls: [],
        sessions: get().sessions.filter((s) => s.sessionId !== sessionId),
      });
    } else {
      set({
        sessions: state.sessions.filter((s) => s.sessionId !== sessionId),
      });
    }
  },

  upsertSession: (session) => {
    set((s) => {
      const idx = s.sessions.findIndex((x) => x.sessionId === session.sessionId);
      if (idx >= 0) {
        const updated = [...s.sessions];
        updated[idx] = { ...updated[idx], ...session };
        return { sessions: updated };
      }
      return { sessions: [session, ...s.sessions] };
    });
  },

  setActiveSession: (sessionId) => {
    set((s) => {
      if (s.activeSessionId === sessionId) return s;
      return {
        activeSessionId: sessionId,
        messages: [],
        toolCalls: [],
      };
    });
    get().upsertSession({ sessionId, status: "active", sandboxId: sessionId });
  },
}));

export { defaultWsUrl };
