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

  private sessionId = "";
  /** True after initialize + session/new for the current WS pairing */
  private acpSessionReady = false;

  async connect(wsUrl: string, token: string, sessionId?: string): Promise<unknown> {
    this.wsUrl = wsUrl;
    this.token = token;
    // Preserve existing sessionId on reconnect when arg omitted
    if (sessionId) this.sessionId = sessionId;
    this.intentionalClose = false;
    this.acpSessionReady = false;

    if (!this.sessionId) {
      return Promise.reject(new Error("session_id is required for WebSocket connect"));
    }

    const params = new URLSearchParams()
    if (token) params.set("token", token)
    params.set("session_id", this.sessionId)
    params.set("role", "browser")
    const queryStr = params.toString()
    const fullUrl = queryStr ? `${wsUrl}?${queryStr}` : wsUrl

    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(fullUrl);

      this.ws.onopen = () => {
        // Relay is a bridge only. ACP initialize/session/new run once the
        // agent is paired (see ensureAcpSession).
        resolve(true);
      };

      this.ws.onmessage = (event) => {
        this.handleMessage(event.data);
      };

      this.ws.onclose = (event) => {
        this.acpSessionReady = false;
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

  isAcpReady(): boolean {
    return this.acpSessionReady;
  }

  /**
   * Full ACP handshake required by Rust webuild agent.
   * Pins session id via `_meta.sessionId` so Relay UUID == ACP sessionId.
   */
  async ensureAcpSession(cwd = "/workspace", sessionId?: string): Promise<string> {
    const sid = sessionId || this.sessionId;
    if (!sid) throw new Error("sessionId is required for ACP session");
    if (this.acpSessionReady && this.sessionId === sid) return sid;

    await this.initialize();
    const { sessionId: created } = await this.newSession(cwd, sid);
    this.sessionId = created || sid;
    this.acpSessionReady = true;
    return this.sessionId;
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

  async initialize(): Promise<unknown> {
    // Do NOT advertise client FS/terminal capabilities. The ACS sandbox agent
    // must use its local /workspace filesystem. Claiming fs.readTextFile here
    // caused the agent to call fs/read_text_file on the browser and hang forever
    // because Web IDE never implements those client methods.
    return this.sendRequest("initialize", {
      protocolVersion: 1,
      clientCapabilities: {
        fs: { readTextFile: false, writeTextFile: false },
        terminal: false,
      },
      clientInfo: { name: "webuild-web-ide", version: "0.1.0" },
      _meta: { clientIdentifier: "webuild-web", clientType: "webuild-web" },
    });
  }

  async newSession(
    cwd: string,
    sessionId?: string,
  ): Promise<{ sessionId: string }> {
    const params: Record<string, unknown> = {
      cwd,
      mcpServers: [],
    };
    if (sessionId) {
      // Rust MvpAgent uses _meta.sessionId to reuse the Relay UUID
      params._meta = { sessionId, yoloMode: true };
    }
    const result = await this.sendRequest("session/new", params);
    return result as { sessionId: string };
  }

  async prompt(sessionId: string, text: string): Promise<unknown> {
    if (!this.acpSessionReady) {
      await this.ensureAcpSession("/workspace", sessionId);
    }
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
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    // Inbound agent request → send JSON-RPC response (not resolve our outbound map)
    this.ws.send(
      JSON.stringify({
        jsonrpc: "2.0",
        id: requestId,
        result: { outcome: { outcome: "selected", optionId } },
      }),
    );
  }

  rejectPermission(requestId: number) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(
      JSON.stringify({
        jsonrpc: "2.0",
        id: requestId,
        result: { outcome: { outcome: "cancelled" } },
      }),
    );
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

      // LLM turns can exceed 30s; session setup can also be slow in sandbox
      const timeoutMs =
        method === "session/prompt" ? 180000 :
        method === "session/new" || method === "initialize" ? 60000 :
        30000;
      setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          reject(new Error(`Request ${method} timed out`));
        }
      }, timeoutMs);
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
    // Never reconnect without a session — relay requires session_id
    if (!this.sessionId) return;
    const delay = Math.min(1000 * Math.pow(2, Math.random() * 3), 30000);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect(this.wsUrl, this.token, this.sessionId).catch(() => {
        this.scheduleReconnect();
      });
    }, delay);
  }
}
