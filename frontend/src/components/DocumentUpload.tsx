// DocumentUpload — drag-and-drop / file-picker upload card.
// Ported from raggles plus the NEW "Original folder path" input: an optional
// provenance field recording where the files really live on the network
// (e.g. \\server\share\ProjectA). Sent as original_base_path on batch
// uploads and joined client-side with the filename for single uploads.
// Also NEW: a separated "Ingest server folder" section (backend reads a
// directory it can already access — no browser upload), and a health-driven
// ingest guard that disables ALL entry points when the embedder/LLM is down.
import { useState, useCallback, useRef } from 'react'
import { uploadDocument, uploadBatch, ingestServerPath } from '../api'
import type { HealthStatus } from '../types'

interface Props {
  onBatchStarted: (id: string) => void
  // Latest /health snapshot from App — null/undefined until the first poll
  // lands (in which case we do NOT block ingestion).
  health?: HealthStatus | null
}

// Join a folder path and a filename following the FOLDER's separator style
// (mirrors the backend's join_original_path rule for consistency).
function joinPath(base: string, name: string): string {
  const trimmed = base.trim().replace(/[\\/]+$/, '')
  if (!trimmed) return ''
  // Windows style when the base starts with \\ or contains any backslash.
  const isWindows = trimmed.startsWith('\\\\') || trimmed.includes('\\')
  return isWindows ? `${trimmed}\\${name}` : `${trimmed}/${name}`
}

export default function DocumentUpload({ onBatchStarted, health }: Props) {
  // Drag-hover visual state.
  const [dragOver, setDragOver] = useState(false)
  // Status/error message shown under the buttons.
  const [message, setMessage] = useState('')
  const [uploading, setUploading] = useState(false)
  // NEW: the optional original-folder provenance value (shared by both the
  // browser-upload path and the server-folder ingest path).
  const [originalBase, setOriginalBase] = useState('')
  // NEW: server-folder ingest state — the directory path on the backend
  // host, its own busy flag, and its own inline status/error message.
  const [serverPath, setServerPath] = useState('')
  const [serverBusy, setServerBusy] = useState(false)
  const [serverMsg, setServerMsg] = useState<{ text: string; error: boolean } | null>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)

  // Ingest guard: block ALL ingestion when the embedder or LLM is known to
  // be unreachable — documents would only fail mid-pipeline. Unknown health
  // (null — /health hasn't answered yet) deliberately does NOT block.
  const ingestBlocked = health != null && (!health.embedder || !health.llm)
  // Browser-upload controls share one disabled condition.
  const uploadDisabled = uploading || ingestBlocked

  // Route the chosen files to the right upload endpoint.
  const handleFiles = async (files: FileList | File[]) => {
    // Guard the drag-drop path too — the drop zone can't be "disabled".
    if (ingestBlocked) return
    const fileArray = Array.from(files)
    if (fileArray.length === 0) return

    setUploading(true)
    setMessage('')

    try {
      // A single .zip goes up as an archive; a single other file goes to the
      // single-document endpoint; anything else is a multi-file batch.
      const isZip = fileArray.length === 1 && fileArray[0].name.toLowerCase().endsWith('.zip')

      let result
      if (fileArray.length === 1 && !isZip) {
        // Single upload: provenance = folder + this file's name.
        result = await uploadDocument(fileArray[0], joinPath(originalBase, fileArray[0].name) || undefined)
      } else if (isZip) {
        // ZIP: backend joins the base with each entry's relative path.
        result = await uploadBatch([], fileArray[0], originalBase.trim() || undefined)
      } else {
        // Multi-file batch: same server-side join per file.
        result = await uploadBatch(fileArray, undefined, originalBase.trim() || undefined)
      }

      // Hand the batch id to the parent so progress polling starts.
      onBatchStarted(result.batch_id)

      // Surface any files rejected for unsupported extensions.
      if (result.skipped_unsupported.length > 0) {
        setMessage(`Skipped unsupported: ${result.skipped_unsupported.join(', ')}`)
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  // Drag-and-drop handler.
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [originalBase, ingestBlocked])

  // File-picker handler (both pickers share it).
  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files)
    }
  }

  // NEW: kick off a server-folder ingest for the typed backend directory.
  const handleServerIngest = async () => {
    const path = serverPath.trim()
    if (!path || serverBusy || ingestBlocked) return

    setServerBusy(true)
    setServerMsg(null)

    try {
      // Reuses the shared original-base value as the citation base path
      // ("" when the user left it blank — the backend accepts that).
      const result = await ingestServerPath(path, originalBase.trim())

      // Same hand-off as browser uploads: parent starts progress polling.
      onBatchStarted(result.batch_id)

      // Surface any files skipped for unsupported extensions.
      if (result.skipped_unsupported.length > 0) {
        setServerMsg({ text: `Skipped unsupported: ${result.skipped_unsupported.join(', ')}`, error: false })
      }
    } catch (err) {
      // 400/403 backend `detail` strings land here verbatim (via api.ts),
      // e.g. "Server-folder ingest is disabled (INGEST_ROOTS is not set)".
      setServerMsg({
        text: err instanceof Error ? err.message : 'Server-folder ingest failed',
        error: true,
      })
    } finally {
      setServerBusy(false)
    }
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={`glass rounded-2xl p-8 text-center border-2 border-dashed transition-all ${dragOver ? 'border-cyan-400/50 bg-cyan-400/5' : 'border-theme-main'}`}
    >
      {/* Ingest guard banner — shown whenever /health reports a hard outage. */}
      {ingestBlocked && (
        <div className="max-w-md mx-auto mb-4 rounded-lg bg-rose-400/10 border border-rose-400/30 px-3 py-2 text-xs text-rose-300">
          Backend embedding/LLM service unreachable &mdash; ingestion disabled
        </div>
      )}

      <p className="text-theme-secondary mb-3">
        {uploading ? 'Uploading...' : 'Drag and drop files here, or click to browse'}
      </p>

      {/* NEW: provenance input — where these files originally live. */}
      <div className="max-w-md mx-auto mb-4 text-left">
        <label htmlFor="original-base" className="block text-xs text-theme-tertiary mb-1">
          Original folder path <span className="opacity-60">(optional — recorded for citation links)</span>
        </label>
        <input
          id="original-base"
          type="text"
          value={originalBase}
          onChange={(e) => setOriginalBase(e.target.value)}
          disabled={uploading || serverBusy}
          placeholder={'\\\\server\\share\\ProjectA'}
          className="w-full rounded-lg bg-[var(--bg-surface)] border border-theme-main px-3 py-2 text-sm font-mono text-theme-primary focus:outline-none focus:ring-2 focus:ring-cyan-400/40 placeholder:text-theme-tertiary transition-all"
        />
      </div>

      {/* The two pickers: files and whole folders. */}
      <div className="flex gap-2 justify-center">
        <input
          type="file"
          accept=".pdf,.docx,.xlsx,.xls,.zip"
          onChange={handleFileInput}
          disabled={uploadDisabled}
          className="hidden"
          id="file-upload"
          multiple
        />
        <label
          htmlFor="file-upload"
          className={`inline-block px-4 py-2 glass-accent text-white text-sm font-medium rounded-xl cursor-pointer hover:brightness-110 transition-all ${uploadDisabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          Choose Files
        </label>
        <input
          type="file"
          ref={folderInputRef}
          onChange={handleFileInput}
          disabled={uploadDisabled}
          className="hidden"
          id="folder-upload"
          /* @ts-expect-error webkitdirectory is non-standard */
          webkitdirectory=""
          multiple
        />
        <label
          htmlFor="folder-upload"
          className={`inline-block px-4 py-2 glass text-theme-secondary text-sm font-medium rounded-xl cursor-pointer hover:bg-[var(--bg-surface)] transition-all ${uploadDisabled ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          Upload Folder
        </label>
      </div>
      <p className="text-xs text-theme-tertiary mt-2">PDF, DOCX, XLSX, ZIP supported — multiple files or folders</p>
      {message && <p className="mt-3 text-sm text-theme-secondary">{message}</p>}

      {/* ---- NEW: server-folder ingest — clearly separated from the browser
           upload controls above. The backend reads the directory itself, so
           the path must sit inside its INGEST_ROOTS allowlist. ---- */}
      <div className="max-w-md mx-auto mt-6 pt-5 border-t border-theme-main text-left">
        <label htmlFor="server-path" className="block text-xs text-theme-tertiary mb-1">
          Ingest server folder <span className="opacity-60">(directory path on the backend host)</span>
        </label>
        <div className="flex gap-2">
          <input
            id="server-path"
            type="text"
            value={serverPath}
            onChange={(e) => setServerPath(e.target.value)}
            // Enter in the path field triggers the same ingest as the button.
            onKeyDown={(e) => { if (e.key === 'Enter') handleServerIngest() }}
            disabled={serverBusy}
            placeholder="/srv/corpora/testdata"
            className="flex-1 min-w-0 rounded-lg bg-[var(--bg-surface)] border border-theme-main px-3 py-2 text-sm font-mono text-theme-primary focus:outline-none focus:ring-2 focus:ring-cyan-400/40 placeholder:text-theme-tertiary transition-all"
          />
          <button
            onClick={handleServerIngest}
            disabled={serverBusy || ingestBlocked || !serverPath.trim()}
            className={`shrink-0 px-4 py-2 glass-accent text-white text-sm font-medium rounded-xl hover:brightness-110 transition-all ${serverBusy || ingestBlocked || !serverPath.trim() ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {serverBusy ? 'Starting...' : 'Ingest'}
          </button>
        </div>
        <p className="text-xs text-theme-tertiary mt-1">
          Uses the original folder path above as the citation base for these files.
        </p>
        {/* Inline result: backend 400/403 detail strings, or skip notices. */}
        {serverMsg && (
          <p className={`mt-2 text-sm ${serverMsg.error ? 'text-rose-300' : 'text-theme-secondary'}`}>
            {serverMsg.text}
          </p>
        )}
      </div>
    </div>
  )
}
