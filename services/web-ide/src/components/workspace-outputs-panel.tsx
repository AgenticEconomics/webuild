'use client'

import { useCallback, useEffect, useState } from 'react'
import { Download, FolderOpen, Loader2, RefreshCw } from 'lucide-react'
import { downloadSandboxFile, listSandboxFiles, type SandboxFileInfo } from '@/lib/gateway-api'
import { useI18n } from '@/lib/i18n'

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function WorkspaceOutputsPanel({
  sandboxId,
  enabled,
}: {
  sandboxId: string
  enabled: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [files, setFiles] = useState<SandboxFileInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!enabled || !sandboxId) return
    setLoading(true)
    setError('')
    try {
      const rows = await listSandboxFiles(sandboxId, 'outputs')
      setFiles(rows)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'List failed')
    } finally {
      setLoading(false)
    }
  }, [enabled, sandboxId])

  useEffect(() => {
    if (open && enabled) refresh()
  }, [open, enabled, refresh])

  const onDownload = async (path: string) => {
    setDownloading(path)
    try {
      await downloadSandboxFile(sandboxId, path)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Download failed')
    } finally {
      setDownloading(null)
    }
  }

  return (
    <div className="border-b border-console-border bg-console-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-console-muted transition-colors hover:bg-console-bg hover:text-console-ink sm:px-5"
      >
        <FolderOpen className="h-3.5 w-3.5" />
        <span className="font-medium">{t('outputsPanel')}</span>
        <span className="text-console-faint">({files.length || '—'})</span>
        <span className="ml-auto flex items-center gap-2">
          {open && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation()
                refresh()
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.stopPropagation()
                  refresh()
                }
              }}
              className="rounded p-1 text-console-faint hover:bg-console-border hover:text-console-ink"
              title={t('refreshOutputs')}
            >
              {loading ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
            </span>
          )}
          <span className="text-console-faint">{open ? '▾' : '▸'}</span>
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 sm:px-5">
          {!enabled && (
            <p className="py-2 text-xs text-console-faint">{t('outputsNeedSandbox')}</p>
          )}
          {error && <p className="py-1 text-xs text-console-danger">{error}</p>}
          {enabled && !loading && files.length === 0 && !error && (
            <p className="py-2 text-xs text-console-faint">{t('outputsEmpty')}</p>
          )}
          {files.length > 0 && (
            <ul className="max-h-40 space-y-1 overflow-y-auto rounded border border-console-border bg-console-bg p-2">
              {files.map((f) => (
                <li
                  key={f.path}
                  className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-console-surface"
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-console-ink" title={f.path}>
                    {f.path.replace(/^outputs\//, '')}
                  </span>
                  <span className="flex-shrink-0 text-console-faint">{formatSize(f.size)}</span>
                  <button
                    type="button"
                    onClick={() => onDownload(f.path)}
                    disabled={downloading === f.path}
                    className="flex-shrink-0 rounded p-1 text-console-blue hover:bg-console-blue-soft disabled:opacity-40"
                    title={t('downloadFile')}
                  >
                    {downloading === f.path ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Download className="h-3.5 w-3.5" />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[10px] text-console-faint">{t('outputsTtlHint')}</p>
        </div>
      )}
    </div>
  )
}
