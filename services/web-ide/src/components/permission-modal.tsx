"use client";

import { useState } from "react";
import type { PermissionRequest } from "@/lib/acp-client";

interface Props {
  request: PermissionRequest;
  onApprove: (optionId: string) => void;
  onReject: () => void;
}

export function PermissionModal({ request, onApprove, onReject }: Props) {
  const [responding, setResponding] = useState(false);

  const handleOption = async (optionId: string, kind: string) => {
    setResponding(true);
    if (kind.startsWith("allow")) {
      onApprove(optionId);
    } else {
      onReject();
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-zinc-800 rounded-xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden">
        <div className="px-6 py-4 border-b border-zinc-700">
          <h2 className="text-lg font-semibold text-zinc-100">
            Permission Required
          </h2>
          <p className="text-sm text-zinc-400 mt-1">
            The agent needs your approval to proceed
          </p>
        </div>

        <div className="px-6 py-4">
          <div className="bg-zinc-900 rounded-lg p-3 mb-4">
            <div className="text-sm font-mono text-zinc-300">
              {String(request.toolCall?.title || "Unknown operation")}
            </div>
            {request.toolCall?.kind != null && (
              <div className="text-xs text-zinc-500 mt-1">
                Type: {String(request.toolCall.kind)}
              </div>
            )}
            {request.toolCall?.rawInput != null && (
              <pre className="text-xs text-zinc-400 mt-2 overflow-x-auto max-h-32">
                {typeof request.toolCall.rawInput === "string"
                  ? request.toolCall.rawInput
                  : JSON.stringify(request.toolCall.rawInput, null, 2)}
              </pre>
            )}
          </div>

          <div className="flex gap-3 justify-end">
            {request.options.map((opt) => (
              <button
                key={opt.optionId}
                onClick={() => handleOption(opt.optionId, opt.kind)}
                disabled={responding}
                className={`px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 ${
                  opt.kind.startsWith("allow")
                    ? "bg-green-600 text-white hover:bg-green-700"
                    : "bg-zinc-600 text-zinc-200 hover:bg-zinc-500"
                }`}
              >
                {opt.name}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
