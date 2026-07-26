"use client";

import { useSessionStore } from "@/stores/session-store";

export function SessionList() {
  const { sessions, activeSessionId, createSession } = useSessionStore();

  const handleNewSession = async () => {
    try {
      await createSession("/workspace");
    } catch (e) {
      console.error("Failed to create session:", e);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-zinc-700">
        <button
          onClick={handleNewSession}
          className="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 text-sm font-medium"
        >
          + New Session
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="text-zinc-500 text-sm text-center py-8">
            No sessions yet
          </div>
        ) : (
          sessions.map((session) => (
            <div
              key={session.sessionId}
              className={`px-3 py-2 border-b border-zinc-800 cursor-pointer hover:bg-zinc-800 ${
                session.sessionId === activeSessionId ? "bg-zinc-800" : ""
              }`}
            >
              <div className="text-sm text-zinc-200 truncate">
                {session.title || session.sessionId.slice(0, 12)}
              </div>
              <div className="text-xs text-zinc-500">{session.status}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
