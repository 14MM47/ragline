// DocumentTree — the Documents tab's folder explorer view.
// NEW in ragline. Groups every ingested document by where it was uploaded
// FROM, using the two coordinates the listing endpoint derives per row:
//   upload_root  the network folder the upload came from (or a batch label
//                when unknown / ACL-hidden for this user) -> top-level node
//   folder_path  the directory part of the upload-relative path -> sub-folders
// On top of that derived tree sits the shared LAYOUT (GET /documents/layout):
//   folders      user-created folders, which exist even while empty
//   placements   "show document X in folder Y instead" overrides
// Both use the same (root, folder_path) coordinates, so a document can be
// moved into a derived folder or a user folder alike. The tree is purely a
// re-arrangement of the same rows the flat table shows: nothing in storage,
// Qdrant or retrieval changes. Expand/collapse state lives in localStorage.
// Skipped duplicates (byte-identical re-uploads the worker did not ingest)
// are NOT drawn as empty rows: the tree shows the INGESTED copy at the
// duplicate's location instead (an alias, with the real stats and the real
// id for selection), and the marker rows themselves sit in a separate
// "Skipped duplicates" list behind a toolbar button, where they can be
// deleted.
import { useCallback, useMemo, useState } from 'react'
import type { Document, FolderRef, Layout, LayoutPlacement } from '../types'
import { basename, CopyPathButton, DocActions, StatusPill, VersionBadge } from './DocumentRowParts'

// localStorage key for per-folder expand/collapse overrides.
const OPEN_KEY = 'ragline_doc_tree_open'

// Root label for rows whose upload_root came back blank (never expected —
// the server always fills it — but the tree must not lose a document).
const FALLBACK_ROOT = 'Unfiled uploads'

// One folder node. `key` is "<root>|<folder_path>": unique per folder and
// what the expand-state map is keyed by.
export interface TreeNode {
  key: string
  root: string
  folderPath: string
  name: string
  depth: number
  // True when a user-created folder row backs this node (deletable when empty).
  virtual: boolean
  // Sub-folders and files, both sorted for display.
  folders: TreeNode[]
  docs: TreeEntry[]
  // Documents anywhere beneath this node (for the folder row's count).
  total: number
  // Documents still pending/processing beneath this node (progress hint).
  inFlight: number
  // Every document id beneath this node (drives the folder's tri-state tick).
  docIds: string[]
}

// One file row: the document drawn, plus — for an alias — the skipped
// duplicate marker row whose location this is.
export interface TreeEntry {
  doc: Document
  via?: Document
}

const nodeKey = (root: string, folderPath: string) => `${root}|${folderPath}`

// Split the listing into what the tree draws and the skipped-duplicate
// marker rows. A marker whose ingested twin is still present becomes an
// alias of that twin at the marker's own location; a marker whose twin is
// gone only appears in the skipped list (it has nothing to show).
export function partitionDocs(docs: Document[]): { entries: TreeEntry[]; skipped: Document[] } {
  const byId = new Map(docs.map((d) => [d.id, d]))
  const entries: TreeEntry[] = []
  const skipped: Document[] = []
  for (const doc of docs) {
    if (doc.status !== 'skipped_duplicate') { entries.push({ doc }); continue }
    skipped.push(doc)
    const twin = doc.duplicate_of ? byId.get(doc.duplicate_of) : undefined
    if (twin) entries.push({ doc: twin, via: doc })
  }
  return { entries, skipped }
}

// Build the folder tree from the flat document list plus the shared layout.
export function buildTree(entries: TreeEntry[], layout: Layout): TreeNode[] {
  const roots = new Map<string, TreeNode>()
  // Folder children are kept in maps while building, then sorted into arrays.
  const childMaps = new Map<TreeNode, Map<string, TreeNode>>()
  const childrenOf = (node: TreeNode) => {
    let m = childMaps.get(node)
    if (!m) { m = new Map(); childMaps.set(node, m) }
    return m
  }
  const mk = (root: string, folderPath: string, name: string, depth: number): TreeNode =>
    ({ key: nodeKey(root, folderPath), root, folderPath, name, depth, virtual: false, folders: [], docs: [], total: 0, inFlight: 0, docIds: [] })

  // Walk (creating) the chain of nodes for (root, folderPath); returns it.
  const chainFor = (root: string, folderPath: string): TreeNode[] => {
    let node = roots.get(root)
    if (!node) { node = mk(root, '', root, 0); roots.set(root, node) }
    const chain: TreeNode[] = [node]
    const segments = folderPath ? folderPath.split('/').filter(Boolean) : []
    let path = ''
    for (const seg of segments) {
      path = path ? `${path}/${seg}` : seg
      const kids = childrenOf(node)
      let child = kids.get(seg)
      if (!child) { child = mk(root, path, seg, node.depth + 1); kids.set(seg, child) }
      node = child
      chain.push(node)
    }
    return chain
  }

  // User folders first so an empty one still shows up.
  for (const f of layout.folders) {
    const chain = chainFor(f.root, f.folder_path)
    chain[chain.length - 1].virtual = true
  }

  // Documents: a placement overrides the derived coordinates. An alias sits
  // where its MARKER row was uploaded (or moved) to; the drawn document is
  // the ingested twin, so counts and selection use the twin's id.
  const placed = new Map(layout.placements.map((p) => [p.document_id, p]))
  for (const entry of entries) {
    const here = entry.via ?? entry.doc
    const p = placed.get(here.id)
    const root = p ? p.root : (here.upload_root || FALLBACK_ROOT)
    const folderPath = p ? p.folder_path : here.folder_path
    const chain = chainFor(root, folderPath)
    chain[chain.length - 1].docs.push(entry)
    // Roll the counts up every ancestor.
    const busy = entry.doc.status === 'pending' || entry.doc.status === 'processing'
    for (const n of chain) { n.total += 1; n.docIds.push(entry.doc.id); if (busy) n.inFlight += 1 }
  }

  // Finalise: attach sorted folder arrays and sort files by name.
  const byName = (a: { name: string }, b: { name: string }) =>
    a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' })
  const finalise = (node: TreeNode) => {
    node.folders = [...(childMaps.get(node)?.values() ?? [])].sort(byName)
    node.docs.sort((a, b) => byName({ name: basename(a.doc.filename) }, { name: basename(b.doc.filename) }))
    // A twin drawn twice under one folder (its own row + an alias) is ONE
    // document: it ticks once and counts once in the folder's "N files".
    node.docIds = [...new Set(node.docIds)]
    node.total = node.docIds.length
    node.folders.forEach(finalise)
  }
  const out = [...roots.values()].sort(byName)
  out.forEach(finalise)
  return out
}

// Every folder node in display order (for the Move-to picker).
function flatten(tree: TreeNode[]): TreeNode[] {
  const out: TreeNode[] = []
  const walk = (n: TreeNode) => { out.push(n); n.folders.forEach(walk) }
  tree.forEach(walk)
  return out
}

// Read the persisted expand/collapse overrides (folder key -> open?).
function loadOpen(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(OPEN_KEY)
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {}
  } catch {
    return {}
  }
}

// Layout edits the tree can ask its owner to perform. Each resolves once the
// server has accepted the change and the owner has re-fetched.
export interface LayoutActions {
  createFolder: (ref: FolderRef) => Promise<void>
  deleteFolder: (ref: FolderRef) => Promise<void>
  move: (id: string, ref: FolderRef) => Promise<void>
  unmove: (id: string) => Promise<void>
}

interface Props {
  docs: Document[]
  layout: Layout
  onDelete: (id: string) => void
  onRetry: (id: string) => void
  retryingIds: Set<string>
  actions: LayoutActions
  // Retrieval scope: ticked document ids, and the bulk tick/untick setter.
  scope: Set<string>
  onSelect: (ids: string[], selected: boolean) => void
  // Delete skipped-duplicate marker rows (one confirm for the lot).
  onDeleteSkipped: (ids: string[]) => void
}

export default function DocumentTree({ docs, layout, onDelete, onRetry, retryingIds, actions, scope, onSelect, onDeleteSkipped }: Props) {
  const { entries, skipped } = useMemo(() => partitionDocs(docs), [docs])
  const byId = useMemo(() => new Map(docs.map((d) => [d.id, d])), [docs])
  const tree = useMemo(() => buildTree(entries, layout), [entries, layout])
  const allFolders = useMemo(() => flatten(tree), [tree])
  const placements = useMemo(() => new Map(layout.placements.map((p) => [p.document_id, p])), [layout])
  // Skipped-duplicates list shown in place of the tree.
  const [showSkipped, setShowSkipped] = useState(false)
  // Expand overrides; folders without an entry use the default (roots open,
  // sub-folders closed) so a big corpus does not unfold on first visit.
  const [open, setOpen] = useState<Record<string, boolean>>(loadOpen)
  const isOpen = useCallback((node: TreeNode) => open[node.key] ?? node.depth === 0, [open])

  const persist = (next: Record<string, boolean>) => {
    setOpen(next)
    try { localStorage.setItem(OPEN_KEY, JSON.stringify(next)) } catch { /* quota / private mode */ }
  }
  const toggle = (node: TreeNode) => persist({ ...open, [node.key]: !isOpen(node) })

  // Expand/collapse everything: one override per folder in the tree.
  const setAll = (value: boolean) => {
    const next: Record<string, boolean> = {}
    const walk = (n: TreeNode) => { next[n.key] = value; n.folders.forEach(walk) }
    tree.forEach(walk)
    persist(next)
  }

  // "New folder" under a node (or a new root when node is null). A plain
  // prompt keeps this pass small; the name is validated server-side too.
  const newFolder = async (parent: TreeNode | null) => {
    const name = prompt(parent ? `New folder inside "${parent.name}":` : 'New top-level folder name:')
    if (!name || !name.trim()) return
    const ref: FolderRef = parent
      ? { root: parent.root, folder_path: parent.folderPath ? `${parent.folderPath}/${name.trim()}` : name.trim() }
      : { root: name.trim(), folder_path: '' }
    await actions.createFolder(ref)
    // Open the parent so the new folder is visible.
    if (parent) persist({ ...open, [parent.key]: true })
  }

  return (
    <div className="glass rounded-2xl overflow-x-auto">
      {/* Toolbar: new root folder, expand/collapse all. */}
      <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-theme-main text-xs">
        <button onClick={() => newFolder(null)} className="text-theme-secondary hover:text-[var(--accent)] transition-colors">
          + New top-level folder
        </button>
        <div className="flex items-center gap-3">
          {/* Skipped-duplicates list toggle (left of expand/collapse). */}
          {skipped.length > 0 && (
            <button
              onClick={() => setShowSkipped((v) => !v)}
              className={`px-2 py-0.5 rounded-md transition-colors ${showSkipped ? 'glass-accent text-white' : 'text-amber-300 hover:text-amber-200'}`}
              title="Byte-identical re-uploads the worker did not ingest"
            >
              Skipped duplicates ({skipped.length})
            </button>
          )}
          <button onClick={() => setAll(true)} className="text-theme-tertiary hover:text-theme-primary transition-colors">
            Expand all
          </button>
          <button onClick={() => setAll(false)} className="text-theme-tertiary hover:text-theme-primary transition-colors">
            Collapse all
          </button>
        </div>
      </div>
      {showSkipped && skipped.length > 0 ? (
        <SkippedList skipped={skipped} byId={byId} onDelete={onDeleteSkipped} />
      ) : (
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-theme-main">
            <th className="pl-4 py-3 w-px"></th>
            <th className="px-4 py-3 text-left font-medium text-theme-secondary">Name</th>
            <th className="px-4 py-3 text-left font-medium text-theme-secondary">Type</th>
            <th className="px-4 py-3 text-left font-medium text-theme-secondary">Pages</th>
            <th className="px-4 py-3 text-left font-medium text-theme-secondary">Chunks</th>
            <th className="px-4 py-3 text-left font-medium text-theme-secondary">Status</th>
            <th className="px-4 py-3 text-left font-medium text-theme-secondary">Uploaded</th>
            {/* w-px + nowrap sizes the actions column to its content. */}
            <th className="px-4 py-3 w-px whitespace-nowrap"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border-subtle)]">
          {tree.map((root) => (
            <FolderRows
              key={root.key}
              node={root}
              isOpen={isOpen}
              onToggle={toggle}
              onNewFolder={newFolder}
              onDeleteFolder={(n) => actions.deleteFolder({ root: n.root, folder_path: n.folderPath })}
              allFolders={allFolders}
              placements={placements}
              actions={actions}
              onDelete={onDelete}
              onRetry={onRetry}
              retryingIds={retryingIds}
              scope={scope}
              onSelect={onSelect}
              onDeleteSkipped={onDeleteSkipped}
            />
          ))}
        </tbody>
      </table>
      )}
    </div>
  )
}

/** The skipped-duplicate marker rows: what was uploaded, what it duplicates, delete. */
function SkippedList({ skipped, byId, onDelete }: {
  skipped: Document[]
  byId: Map<string, Document>
  onDelete: (ids: string[]) => void
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-theme-main">
          <th className="px-4 py-3 text-left font-medium text-theme-secondary">Skipped upload</th>
          <th className="px-4 py-3 text-left font-medium text-theme-secondary">Ingested copy</th>
          <th className="px-4 py-3 text-left font-medium text-theme-secondary">Uploaded</th>
          <th className="px-4 py-3 w-px whitespace-nowrap text-right">
            <button onClick={() => onDelete(skipped.map((d) => d.id))} className="text-rose-400 hover:text-rose-300 text-xs font-medium transition-colors">
              Delete all {skipped.length}
            </button>
          </th>
        </tr>
      </thead>
      <tbody className="divide-y divide-[var(--border-subtle)]">
        {skipped.map((doc) => {
          const twin = doc.duplicate_of ? byId.get(doc.duplicate_of) : undefined
          return (
            <tr key={doc.id} className="hover:bg-[var(--bg-surface)] transition-colors">
              <td className="px-4 py-2 text-theme-primary">
                <span className="flex items-center gap-2">
                  <span className="text-theme-tertiary">📄</span>
                  <code className="text-xs break-all" title={doc.filename}>{doc.upload_root}/{doc.filename}</code>
                </span>
              </td>
              <td className="px-4 py-2 text-theme-secondary">
                {twin ? (
                  <code className="text-xs break-all" title={twin.filename}>{twin.upload_root}/{twin.filename}</code>
                ) : (
                  <span className="text-xs text-theme-tertiary">original no longer present</span>
                )}
              </td>
              <td className="px-4 py-2 text-theme-secondary">{new Date(doc.upload_date).toLocaleDateString()}</td>
              <td className="px-4 py-2 w-px whitespace-nowrap text-right">
                <button onClick={() => onDelete([doc.id])} className="text-rose-400 hover:text-rose-300 text-xs transition-colors">
                  Delete
                </button>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// Indent per depth level, applied to the name cell.
const INDENT_PX = 18

// Props threaded unchanged down the recursion.
interface RowContext {
  isOpen: (n: TreeNode) => boolean
  onToggle: (n: TreeNode) => void
  onNewFolder: (parent: TreeNode) => void
  onDeleteFolder: (n: TreeNode) => void
  allFolders: TreeNode[]
  placements: Map<string, LayoutPlacement>
  actions: LayoutActions
  onDelete: (id: string) => void
  onRetry: (id: string) => void
  retryingIds: Set<string>
  scope: Set<string>
  onSelect: (ids: string[], selected: boolean) => void
  onDeleteSkipped: (ids: string[]) => void
}

/** Tri-state checkbox: checked when every id is ticked, indeterminate when some. */
function TriStateBox({ ids, scope, onSelect, title }: {
  ids: string[]
  scope: Set<string>
  onSelect: (ids: string[], selected: boolean) => void
  title: string
}) {
  const ticked = ids.filter((id) => scope.has(id)).length
  const all = ids.length > 0 && ticked === ids.length
  const some = ticked > 0 && !all
  return (
    <input
      type="checkbox"
      checked={all}
      disabled={ids.length === 0}
      // `indeterminate` is not an attribute — set it on the element itself.
      ref={(el) => { if (el) el.indeterminate = some }}
      // A partially ticked folder ticks fully on click; a full one clears.
      onChange={() => onSelect(ids, !all)}
      onClick={(e) => e.stopPropagation()}
      title={title}
    />
  )
}

/** A folder row followed (when open) by its sub-folders and files. */
function FolderRows(props: RowContext & { node: TreeNode }) {
  const { node, isOpen, onToggle, onNewFolder, onDeleteFolder, scope, onSelect } = props
  const open = isOpen(node)
  // A user folder with nothing beneath it may be deleted.
  const deletable = node.virtual && node.total === 0 && node.folders.length === 0
  return (
    <>
      <tr
        className="group hover:bg-[var(--bg-surface)] transition-colors cursor-pointer select-none"
        onClick={() => onToggle(node)}
      >
        <td className="pl-4 py-2 w-px" onClick={(e) => e.stopPropagation()}>
          <TriStateBox ids={node.docIds} scope={scope} onSelect={onSelect} title="Include this folder in retrieval" />
        </td>
        <td className="px-4 py-2 font-medium text-theme-primary" colSpan={6}>
          <span className="flex items-center gap-2" style={{ paddingLeft: node.depth * INDENT_PX }}>
            {/* Disclosure chevron. */}
            <span className={`inline-block w-3 text-theme-tertiary transition-transform ${open ? 'rotate-90' : ''}`}>▸</span>
            {/* Glyph: upload sources (derived roots) get the share glyph,
                user-created folders a hollow one, derived sub-folders a solid one. */}
            <span className="text-theme-tertiary">{node.virtual ? '🗀' : node.depth === 0 ? '🖧' : '📁'}</span>
            <code className={`break-all ${node.depth === 0 ? 'text-xs' : 'text-sm font-sans'}`} title={node.name}>{node.name}</code>
            <span className="text-xs text-theme-tertiary font-normal">
              {node.total} {node.total === 1 ? 'file' : 'files'}
              {node.inFlight > 0 && <span className="text-cyan-300"> · {node.inFlight} in progress</span>}
            </span>
          </span>
        </td>
        {/* Folder actions, revealed on hover. stopPropagation keeps the row's
            expand/collapse from firing under the click. */}
        <td className="px-4 py-2 w-px whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity text-xs">
            <button onClick={() => onNewFolder(node)} className="text-theme-secondary hover:text-[var(--accent)] transition-colors">
              New folder
            </button>
            {deletable && (
              <button onClick={() => onDeleteFolder(node)} className="text-rose-400 hover:text-rose-300 transition-colors">
                Delete
              </button>
            )}
          </div>
        </td>
      </tr>
      {open && node.folders.map((child) => (
        <FolderRows key={child.key} {...props} node={child} />
      ))}
      {open && node.docs.map(({ doc, via }) => (
        <FileRow
          key={via ? via.id : doc.id}
          doc={doc}
          via={via}
          depth={node.depth + 1}
          here={node}
          allFolders={props.allFolders}
          placement={props.placements.get((via ?? doc).id)}
          actions={props.actions}
          onDelete={props.onDelete}
          onDeleteSkipped={props.onDeleteSkipped}
          onRetry={props.onRetry}
          retrying={props.retryingIds.has(doc.id)}
          selected={scope.has(doc.id)}
          onSelect={(v) => onSelect([doc.id], v)}
        />
      ))}
    </>
  )
}

// Sentinel option values for the Move-to picker.
const PICK_NONE = ''
const PICK_RESET = '\u0000reset'

/** One document inside a folder: same cells as the flat table, indented. */
function FileRow({ doc, via, depth, here, allFolders, placement, actions, onDelete, onDeleteSkipped, onRetry, retrying, selected, onSelect }: {
  doc: Document
  // Set on an alias row: the skipped-duplicate marker whose location this is.
  via?: Document
  depth: number
  // The folder this row is drawn in (excluded from its own Move-to list).
  here: TreeNode
  allFolders: TreeNode[]
  placement: LayoutPlacement | undefined
  actions: LayoutActions
  onDelete: (id: string) => void
  onDeleteSkipped: (ids: string[]) => void
  onRetry: (id: string) => void
  retrying: boolean
  // Retrieval-scope tick.
  selected: boolean
  onSelect: (selected: boolean) => void
}) {
  const [picking, setPicking] = useState(false)
  const [busy, setBusy] = useState(false)

  // Move-to picker: choose a folder (any node but this one) or reset.
  const onPick = async (value: string) => {
    if (value === PICK_NONE) { setPicking(false); return }
    setBusy(true)
    try {
      if (value === PICK_RESET) await actions.unmove(doc.id)
      else {
        const target = allFolders.find((n) => n.key === value)
        if (target) await actions.move(doc.id, { root: target.root, folder_path: target.folderPath })
      }
    } finally {
      setBusy(false)
      setPicking(false)
    }
  }

  return (
    <tr className={`group hover:bg-[var(--bg-surface)] transition-colors ${selected ? 'bg-[var(--accent)]/5' : ''}`}>
      <td className="pl-4 py-2 w-px">
        <input type="checkbox" checked={selected} onChange={(e) => onSelect(e.target.checked)} title="Include in retrieval" />
      </td>
      <td className="px-4 py-2 font-medium text-theme-primary min-w-0">
        <span className="flex items-center gap-2" style={{ paddingLeft: depth * INDENT_PX }}>
          <span className="inline-block w-3" />
          <span className="text-theme-tertiary">📄</span>
          <span className="break-all" title={doc.filename}>{basename(doc.filename)}</span>
          <VersionBadge version={doc.version} />
          {/* Alias marker: this upload was skipped as a byte-identical
              duplicate; the row shows the ingested copy that lives elsewhere. */}
          {via && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-400/15 text-sky-300 shrink-0"
              title={`Duplicate upload skipped on ${new Date(via.upload_date).toLocaleDateString()}; showing the ingested copy at ${doc.upload_root}/${doc.filename}`}
            >
              duplicate
            </span>
          )}
          {/* Moved marker: the row is not where the upload put it. */}
          {placement && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-400/15 text-amber-300 shrink-0"
              title={`Moved here; uploaded to ${doc.upload_root}${doc.folder_path ? '/' + doc.folder_path : ''}`}
            >
              moved
            </span>
          )}
          {/* The full network path is one click away instead of a column:
              the folder rows above already show where the file lives. */}
          {doc.original_path && <CopyPathButton path={doc.original_path} title={doc.original_path} />}
        </span>
      </td>
      <td className="px-4 py-2 text-theme-secondary uppercase">{doc.file_type}</td>
      <td className="px-4 py-2 text-theme-secondary">{doc.page_count}</td>
      <td className="px-4 py-2 text-theme-secondary">{doc.chunk_count}</td>
      <td className="px-4 py-2"><StatusPill doc={doc} /></td>
      <td className="px-4 py-2 text-theme-secondary">{new Date(doc.upload_date).toLocaleDateString()}</td>
      <td className="px-4 py-2 w-px whitespace-nowrap">
        <div className="flex items-center gap-2 text-xs">
          {via ? (
            /* An alias has no state of its own to move or retry: the only
               action is dropping the marker row (the ingested copy stays). */
            <button onClick={() => onDeleteSkipped([via.id])} className="text-rose-400 hover:text-rose-300 transition-colors">
              Remove duplicate
            </button>
          ) : picking ? (
            <select
              autoFocus
              disabled={busy}
              defaultValue={PICK_NONE}
              onChange={(e) => onPick(e.target.value)}
              onBlur={() => !busy && setPicking(false)}
              className="text-xs bg-[var(--bg-surface)] text-theme-primary border border-theme-subtle rounded-md px-1 py-0.5 max-w-[260px]"
            >
              <option value={PICK_NONE}>Move to…</option>
              {placement && <option value={PICK_RESET}>↩ Upload location</option>}
              {allFolders.filter((n) => n.key !== here.key).map((n) => (
                <option key={n.key} value={n.key}>
                  {' '.repeat(n.depth * 2)}{n.depth > 0 ? '└ ' : ''}{n.name}
                </option>
              ))}
            </select>
          ) : (
            <button
              onClick={() => setPicking(true)}
              className="text-theme-secondary hover:text-[var(--accent)] transition-colors opacity-0 group-hover:opacity-100"
            >
              Move
            </button>
          )}
          {!via && <DocActions doc={doc} onDelete={onDelete} onRetry={onRetry} retrying={retrying} />}
        </div>
      </td>
    </tr>
  )
}
