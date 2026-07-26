export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcNotification {
  jsonrpc: "2.0";
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

export interface SessionUpdate {
  sessionUpdate: string;
  content?: { type: string; text?: string };
  toolCallId?: string;
  title?: string;
  kind?: string;
  status?: string;
  rawInput?: unknown;
  rawOutput?: unknown;
  [key: string]: unknown;
}

export interface PermissionRequest {
  id: number;
  sessionId: string;
  toolCall: Record<string, unknown>;
  options: Array<{ optionId: string; name: string; kind: string }>;
}

type SessionUpdateHandler = (sessionId: string, update: SessionUpdate) => void;
type PermissionHandler = (req: PermissionRequest) => void;
type DisconnectHandler = (reason: string) => void;

export class AcpClient {
  private ws: WebSocket | null = null;
  private nextId = 1;
  private pendingRequests = new Map<
    number,
    { resolve: (v: unknown) => void; reject: (e: Error) => void }
  >();
  private sessionUpdateHandlers: SessionUpdateHandler[] = [];
  private permissionHandlers: PermissionHandler[] = [];
  private disconnectHandlers: DisconnectHandler[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private wsUrl = "";
  private token = "";
  private intentionalClose = false;

  async connect(wsUrl: string, token: string): Promise<unknown> {
    this.wsUrl = wsUrl;
    this.token = token;
    this.intentionalClose = false;

    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(`${wsUrl}?token=${token}`);

      this.ws.onopen = async () => {
        try {
          const result = await this.sendRequest("initialize", {
            protocolVersion: { major: 0, minor: 1, patch: 0 },
            clientCapabilities: {},
            clientInfo: { name: "webuild-web-ide", version: "0.1.0" },
          });
          resolve(result);
        } catch (e) {
          reject(e);
        }
      };

      this.ws.onmessage = (event) => {
        this.handleMessage(event.data);
      };

      this.ws.onclose = (event) => {
        if (!this.intentionalClose) {
          this.scheduleReconnect();
        }
        this.disconnectHandlers.forEach((h) => h(event.reason || "connection closed"));
      };

      this.ws.onerror = () => {
        reject(new Error("WebSocket connection failed"));
      };
    });
  }

  disconnect() {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.pendingRequests.clear();
  }

  async newSession(cwd: string): Promise<{ sessionId: string }> {
    const result = await this.sendRequest("session/new", { cwd, mcpServers: [] });
    return result as { sessionId: string };
  }

  async prompt(sessionId: string, text: string): Promise<unknown> {
    return this.sendRequest("session/prompt", {
      sessionId,
      prompt: [{ type: "text", text }],
    });
  }

  cancel(sessionId: string) {
    this.sendNotification("session/cancel", { sessionId });
  }

  async listSessions(): Promise<unknown[]> {
    const result = await this.sendRequest("session/list", {});
    return (result as { sessions: unknown[] })?.sessions || [];
  }

  async respondPermission(requestId: number, optionId: string) {
    const pending = this.pendingRequests.get(requestId);
    if (pending) {
      pending.resolve({ outcome: "selected", optionId });
      this.pendingRequests.delete(requestId);
    }
  }

  rejectPermission(requestId: number) {
    const pending = this.pendingRequests.get(requestId);
    if (pending) {
      pending.resolve({ outcome: "cancelled" });
      this.pendingRequests.delete(requestId);
    }
  }

  onSessionUpdate(handler: SessionUpdateHandler) {
    this.sessionUpdateHandlers.push(handler);
  }

  onPermissionRequest(handler: PermissionHandler) {
    this.permissionHandlers.push(handler);
  }

  onDisconnect(handler: DisconnectHandler) {
    this.disconnectHandlers.push(handler);
  }

  private sendRequest(method: string, params: Record<string, unknown>): Promise<unknown> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error("WebSocket not connected"));
        return;
      }
      const id = this.nextId++;
      this.pendingRequests.set(id, { resolve, reject });
      const msg: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };
      this.ws.send(JSON.stringify(msg));

      setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          reject(new Error(`Request ${method} timed out`));
        }
      }, 30000);
    });
  }

  private sendNotification(method: string, params: Record<string, unknown>) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const msg: JsonRpcNotification = { jsonrpc: "2.0", method, params };
    this.ws.send(JSON.stringify(msg));
  }

  private handleMessage(data: string) {
    try {
      const msg = JSON.parse(data) as JsonRpcResponse & { method?: string; params?: Record<string, unknown> };

      if (msg.id !== undefined && (msg.result !== undefined || msg.error !== undefined)) {
        const pending = this.pendingRequests.get(msg.id);
        if (pending) {
          this.pendingRequests.delete(msg.id);
          if (msg.error) {
            pending.reject(new Error(msg.error.message));
          } else {
            pending.resolve(msg.result);
          }
        }
        return;
      }

      if (msg.method === "session/update") {
        const params = msg.params as { sessionId: string; update: SessionUpdate };
        this.sessionUpdateHandlers.forEach((h) => h(params.sessionId, params.update));
      } else if (msg.method === "session/request_permission") {
        const params = msg.params as {
          sessionId: string;
          toolCall: Record<string, unknown>;
          options: Array<{ optionId: string; name: string; kind: string }>;
        };
        this.permissionHandlers.forEach((h) =>
          h({ id: msg.id!, sessionId: params.sessionId, toolCall: params.toolCall, options: params.options })
        );
      }
    } catch (e) {
      console.error("Failed to parse ACP message:", e, data);
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    const delay = Math.min(1000 * Math.pow(2, Math.random() * 3), 30000);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect(this.wsUrl, this.token).catch(() => {
        this.scheduleReconnect();
      });
    }, delay);
  }
}
