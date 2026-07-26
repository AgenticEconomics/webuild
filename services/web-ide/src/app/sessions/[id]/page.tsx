"use client";

import { useEffect } from "react";
import { ChatPanel } from "@/components/chat-panel";
import { ToolCallList } from "@/components/tool-call-card";
import { SessionList } from "@/components/session-list";
import { useSessionStore } from "@/stores/session-store";

export default function SessionPage({
  params,
}: {
  params: { id: string };
}) {
  const { activeSessionId, toolCalls, isConnected, connect } =
    useSessionStore();

  useEffect(() => {
    if (!isConnected) {
      const wsUrl =
        localStorage.getItem("webuild_ws_url") ||
        process.env.NEXT_PUBLIC_WS_URL ||
        `ws://${window.location.host}/ws/relay`;
      const token = localStorage.getItem("webuild_token") || "";
      connect(wsUrl, token).catch((e) => {
        console.error("WebSocket connection failed:", e);
      });
    }
  }, [isConnected, connect]);

  useEffect(() => {
    if (params.id && params.id !== activeSessionId) {
      useSessionStore.setState({ activeSessionId: params.id });
    }
  }, [params.id, activeSessionId]);

  return (
    <div className="flex h-screen bg-zinc-900 text-zinc-100">
      {/* Sidebar */}
      <aside className="w-64 border-r border-zinc-700 flex-shrink-0">
        <SessionList />
      </aside>

      {/* Main chat area */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-12 border-b border-zinc-700 flex items-center px-4">
          <h1 className="text-sm font-medium text-zinc-300">
            {activeSessionId
              ? `Session: ${activeSessionId.slice(0, 16)}...`
              : "No session"}
          </h1>
          <div className="ml-auto flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                isConnected ? "bg-green-500" : "bg-red-500"
              }`}
            />
            <span className="text-xs text-zinc-500">
              {isConnected ? "Connected" : "Disconnected"}
            </span>
          </div>
        </header>
        <div className="flex-1 overflow-hidden">
          <ChatPanel />
        </div>
      </main>

      {/* Tool calls panel */}
      <aside className="w-80 border-l border-zinc-700 flex-shrink-0 overflow-y-auto">
        <div className="p-3 border-b border-zinc-700">
          <h2 className="text-sm font-medium text-zinc-300">Tool Calls</h2>
        </div>
        <div className="p-3">
          <ToolCallList toolCalls={toolCalls} />
        </div>
      </aside>
    </div>
  );
}
