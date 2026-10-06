// DocumentTree.test — the pure tree-building logic behind the explorer view:
// partitionDocs (skipped duplicates -> aliases) and buildTree (derived
// folders, user folders, placements, per-folder counts and tick ids).
import { describe, expect, it } from 'vitest'
import { buildTree, partitionDocs, type TreeNode } from './DocumentTree'
import type { Document, Layout } from '../types'

// A ready document at (root, folder_path) with sensible defaults.
function doc(id: string, upload_root: string, folder_path: string, extra: Partial<Document> = {}): Document {
  return {
    id,
    filename: folder_path ? `${folder_path}/${id}.pdf` : `${id}.pdf`,
    file_type: 'pdf',
    upload_date: '2026-09-12T08:00:00Z',
    page_count: 1,
    chunk_count: 1,
    status: 'ready',
    stage: '',
    original_path: '',
    version: 1,
    upload_root,
    folder_path,
    duplicate_of: '',
    ...extra,
  }
}

const EMPTY: Layout = { folders: [], placements: [] }

// Find a node by its key ("<root>|<folder_path>"; a root is "<root>|") anywhere in the tree.
function find(tree: TreeNode[], key: string): TreeNode | undefined {
  for (const n of tree) {
    if (n.key === key) return n
    const hit = find(n.folders, key)
    if (hit) return hit
  }
  return undefined
}

describe('partitionDocs', () => {
  it('turns a skipped duplicate into an alias of its ready twin', () => {
    const ready = doc('r1', 'Share', 'a')
    const skipped = doc('s1', 'Share', 'b', { status: 'skipped_duplicate', duplicate_of: 'r1', chunk_count: 0 })
    const { entries, skipped: markers } = partitionDocs([ready, skipped])
    expect(markers.map((d) => d.id)).toEqual(['s1'])
    // The ready row itself, plus an alias entry pointing at the marker.
    expect(entries).toHaveLength(2)
    expect(entries[1]).toEqual({ doc: ready, via: skipped })
  })

  it('keeps an orphaned marker out of the tree', () => {
    const orphan = doc('s2', 'Share', '', { status: 'skipped_duplicate', duplicate_of: 'gone' })
    const { entries, skipped } = partitionDocs([orphan])
    expect(entries).toEqual([])
    expect(skipped).toHaveLength(1)
  })
})

describe('buildTree', () => {
  it('nests derived folders under the upload root and rolls counts up', () => {
    const tree = buildTree(
      partitionDocs([doc('a', 'Share', 'plc/siemens'), doc('b', 'Share', 'plc'), doc('c', 'Share', '')]).entries,
      EMPTY,
    )
    expect(tree.map((n) => n.name)).toEqual(['Share'])
    const root = tree[0]
    expect(root.total).toBe(3)
    expect(root.docs.map((e) => e.doc.id)).toEqual(['c'])
    const plc = find(tree, 'Share|plc')!
    expect(plc.total).toBe(2)
    expect(plc.depth).toBe(1)
    const siemens = find(tree, 'Share|plc/siemens')!
    expect(siemens.total).toBe(1)
    expect(siemens.depth).toBe(2)
    expect(root.docIds.sort()).toEqual(['a', 'b', 'c'])
  })

  it('draws an alias at the marker location and counts the twin once', () => {
    const ready = doc('r1', 'Share', 'old')
    const skipped = doc('s1', 'Share', 'new', { status: 'skipped_duplicate', duplicate_of: 'r1' })
    const tree = buildTree(partitionDocs([ready, skipped]).entries, EMPTY)
    const root = tree[0]
    // Two rows in the tree, one document: the root counts and ticks it once.
    expect(find(tree, 'Share|old')!.docs[0].via).toBeUndefined()
    expect(find(tree, 'Share|new')!.docs[0]).toMatchObject({ doc: { id: 'r1' }, via: { id: 's1' } })
    expect(root.total).toBe(1)
    expect(root.docIds).toEqual(['r1'])
  })

  it('materialises user folders, marks them virtual, and honours placements', () => {
    const layout: Layout = {
      folders: [
        { root: 'Projects', folder_path: 'site-b/plc', created_by: 'u' },
        { root: 'Share', folder_path: 'x', created_by: 'u' },
      ],
      placements: [{ document_id: 'a', root: 'Projects', folder_path: 'site-b/plc' }],
    }
    const tree = buildTree(partitionDocs([doc('a', 'Share', 'plc'), doc('b', 'Share', 'plc')]).entries, layout)
    expect(tree.map((n) => n.name)).toEqual(['Projects', 'Share'])
    // Only the leaf carries the row; its implicit parent is not virtual.
    expect(find(tree, 'Projects|site-b')!.virtual).toBe(false)
    const leaf = find(tree, 'Projects|site-b/plc')!
    expect(leaf.virtual).toBe(true)
    // The placed document moved out of Share/plc into the user folder.
    expect(leaf.docs.map((e) => e.doc.id)).toEqual(['a'])
    expect(find(tree, 'Share|plc')!.docs.map((e) => e.doc.id)).toEqual(['b'])
    expect(find(tree, 'Share|')!.total).toBe(1)
    // An empty user folder still exists, with nothing to tick.
    const empty = find(tree, 'Share|x')!
    expect(empty.total).toBe(0)
    expect(empty.docIds).toEqual([])
  })

  it('places an alias by the marker row, not by the twin', () => {
    const ready = doc('r1', 'Share', 'old')
    const skipped = doc('s1', 'Share', 'new', { status: 'skipped_duplicate', duplicate_of: 'r1' })
    const layout: Layout = { folders: [], placements: [{ document_id: 's1', root: 'Moved', folder_path: '' }] }
    const tree = buildTree(partitionDocs([ready, skipped]).entries, layout)
    expect(find(tree, 'Moved|')!.docs[0]).toMatchObject({ doc: { id: 'r1' }, via: { id: 's1' } })
    expect(find(tree, 'Share|new')).toBeUndefined()
  })

  it('sorts folders and files naturally by name', () => {
    const tree = buildTree(
      partitionDocs([doc('x', 'Share', 'b10'), doc('y', 'Share', 'b2'), doc('z', 'Share', 'a')]).entries,
      EMPTY,
    )
    expect(tree[0].folders.map((n) => n.name)).toEqual(['a', 'b2', 'b10'])
  })
})
