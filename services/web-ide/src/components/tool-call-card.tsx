"use client";

import { useState } from "react";
import type { ToolCall } from "@/stores/session-store";

const STATUS_COLORS: Record<string, string> = {
  pending: "text-yellow-400",
  in_progress: "text-blue-400",
  completed: "text-green-400",
  failed: "text-red-400",
};

const STATUS_ICONS: Record<string, string> = {
  pending: "⏳",
  in_progress: "⚡",
  completed: "✅",
  failed: "❌",
};

export function ToolCallCard({ toolCall }: { toolCall: ToolCall }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border border-zinc-700 rounded-lg overflow-hidden mb-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-zinc-800 hover:bg-zinc-750 text-left"
      >
        <span>{STATUS_ICONS[toolCall.status] || "🔧"}</span>
        <span className="flex-1 text-sm font-mono">{toolCall.title}</span>
        <span className={`text-xs ${STATUS_COLORS[toolCall.status] || ""}`}>
          {toolCall.status}
        </span>
        <span className="text-zinc-500 text-xs">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="px-3 py-2 bg-zinc-900 text-xs space-y-2">
          <div>
            <div className="text-zinc-500 mb-1">Kind: {toolCall.kind}</div>
            <div className="text-zinc-500 mb-1">ID: {toolCall.toolCallId}</div>
          </div>
          {toolCall.rawInput && (
            <div>
              <div className="text-zinc-400 mb-1">Input:</div>
              <pre className="bg-zinc-800 rounded p-2 overflow-x-auto text-zinc-300">
                {typeof toolCall.rawInput === "string"
                  ? toolCall.rawInput
                  : JSON.stringify(toolCall.rawInput, null, 2)}
              </pre>
            </div>
          )}
          {toolCall.rawOutput && (
            <div>
              <div className="text-zinc-400 mb-1">Output:</div>
              <pre className="bg-zinc-800 rounded p-2 overflow-x-auto text-zinc-300 max-h-48 overflow-y-auto">
                {typeof toolCall.rawOutput === "string"
                  ? toolCall.rawOutput
                  : JSON.stringify(toolCall.rawOutput, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolCallList({ toolCalls }: { toolCalls: ToolCall[] }) {
  if (toolCalls.length === 0) {
    return (
      <div className="text-zinc-500 text-sm text-center py-4">
        No tool calls yet
      </div>
    );
  }
  return (
    <div className="space-y-1">
      {toolCalls.map((tc) => (
        <ToolCallCard key={tc.toolCallId} toolCall={tc} />
      ))}
    </div>
  );
}
