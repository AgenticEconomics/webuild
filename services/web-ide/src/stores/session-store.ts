import { create } from "zustand";
import { AcpClient, type SessionUpdate } from "@/lib/acp-client";

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

interface SessionInfo {
  sessionId: string;
  title?: string;
  status: string;
}

interface SessionState {
  client: AcpClient | null;
  isConnected: boolean;
  sessions: SessionInfo[];
  activeSessionId: string | null;
  messages: Message[];
  toolCalls: ToolCall[];

  connect: (wsUrl: string, token: string) => Promise<void>;
  disconnect: () => void;
  createSession: (cwd: string) => Promise<string>;
  sendMessage: (text: string) => Promise<void>;
  cancelCurrent: () => void;
  approvePermission: (requestId: number, optionId: string) => void;
  rejectPermission: (requestId: number) => void;
  loadSessions: () => Promise<void>;
}

let msgCounter = 0;

export const useSessionStore = create<SessionState>((set, get) => ({
  client: null,
  isConnected: false,
  sessions: [],
  activeSessionId: null,
  messages: [],
  toolCalls: [],

  connect: async (wsUrl, token) => {
    const client = new AcpClient();

    client.onSessionUpdate((sessionId, update) => {
      if (sessionId !== get().activeSessionId) return;

      switch (update.sessionUpdate) {
        case "user_message_chunk": {
          const text = (update.content as { text?: string })?.text || "";
          set((s) => {
            const last = s.messages[s.messages.length - 1];
            if (last?.role === "user") {
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
                { id: `msg-${++msgCounter}`, role: "user", content: text, timestamp: Date.now() },
              ],
            };
          });
          break;
        }
        case "agent_message_chunk": {
          const text = (update.content as { text?: string })?.text || "";
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
      set({ isConnected: false });
    });

    await client.connect(wsUrl, token);
    set({ client, isConnected: true });
  },

  disconnect: () => {
    get().client?.disconnect();
    set({ client: null, isConnected: false });
  },

  createSession: async (cwd) => {
    const { client } = get();
    if (!client) throw new Error("Not connected");
    const { sessionId } = await client.newSession(cwd);
    set((s) => ({
      activeSessionId: sessionId,
      sessions: [...s.sessions, { sessionId, status: "active" }],
      messages: [],
      toolCalls: [],
    }));
    return sessionId;
  },

  sendMessage: async (text) => {
    const { client, activeSessionId } = get();
    if (!client || !activeSessionId) return;

    set((s) => ({
      messages: [
        ...s.messages,
        { id: `msg-${++msgCounter}`, role: "user", content: text, timestamp: Date.now() },
      ],
    }));

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
    const { client } = get();
    if (!client) return;
    const sessions = (await client.listSessions()) as SessionInfo[];
    set({ sessions });
  },
}));
