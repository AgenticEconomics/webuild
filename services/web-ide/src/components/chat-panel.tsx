"use client";

import { useState, useRef, useEffect } from "react";
import { useSessionStore, type Message } from "@/stores/session-store";
import { MessageContent } from "@/components/message-content";

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 ${
          isUser ? "bg-blue-600 text-white" : "bg-zinc-800 text-zinc-100"
        }`}
      >
        <div className="text-xs opacity-50 mb-1">
          {isUser ? "You" : "WeBuild"}
        </div>
        <MessageContent content={message.content} plain={isUser} />
      </div>
    </div>
  );
}

export function ChatPanel() {
  const { messages, activeSessionId, isConnected, sendMessage, cancelCurrent } =
    useSessionStore();
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending || !activeSessionId) return;
    setInput("");
    setSending(true);
    try {
      await sendMessage(text);
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (!activeSessionId) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500">
        Select or create a session to start chatting
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-zinc-700 p-4">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isConnected
                ? "Type a message... (Enter to send, Shift+Enter for newline)"
                : "Connecting..."
            }
            disabled={!isConnected}
            rows={2}
            className="flex-1 bg-zinc-800 text-zinc-100 rounded-lg px-4 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          />
          <div className="flex flex-col gap-2">
            <button
              onClick={handleSend}
              disabled={sending || !input.trim()}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {sending ? "..." : "Send"}
            </button>
            <button
              onClick={cancelCurrent}
              disabled={!sending}
              className="bg-zinc-700 text-zinc-300 px-4 py-2 rounded-lg hover:bg-zinc-600 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
