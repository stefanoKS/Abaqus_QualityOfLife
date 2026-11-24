import { useEffect, useRef, useState } from 'react'
import { err, request, type Project, type Revision, type RevisionSummary } from '../../api'
import { reconcile } from './merge'

/**
 * Automatic replacement of the current model's working head.
 *
 * The engineer edits one current model; a valid committed edit becomes the new
 * head without a manual "Save revision" gesture. The store still appends an
 * immutable revision per committed write, so a submitted setup, mesh, deck,
 * job or historical link keeps referring to exactly what it ran.
 *
 * Properties this controller guarantees:
 *
 *  - coalescing: N quick edits within one debounce window produce one revision,
 *    and edits made while a request is in flight are retained and written next;
 *  - one writer per model: writes are serialized, so two responses can never
 *    race to become the base of the next one;
 *  - identity scoping: a late response for a different model or an abandoned
 *    generation is discarded instead of overwriting fresher local state;
 *  - a recoverable concurrent edit: a 409 from another tab keeps the unsent
 *    draft and resolves it with a three-way rebase, so a second window's
 *    independent edit (for example mesh size) never reverts a field the other
 *    window changed (for example reporting width);
 *  - a real same-field conflict is surfaced by path with a Reload choice instead
 *    of overwriting the other engineer's value;
 *  - idempotent recovery from a lost response: before retrying, the current
 *    head is compared with the draft, and an already-committed identical setup
 *    is adopted rather than written twice.
 */
export type SavePhase = 'saved' | 'pending' | 'saving' | 'error'

export interface AutoSaveState {
  phase: SavePhase
  /** Human-readable cause when phase is `error`. */
  error: string
  /** A valid local edit is not committed yet. */
  dirty: boolean
  /** True when the write was rejected by a concurrent edit in another tab. */
  conflict: boolean
  /** Paths that genuinely changed on both sides; a write must not proceed. */
  conflicts: string[]
}

export interface AutoSaver {
  state: AutoSaveState
  /** Record the latest valid draft and schedule one coalesced write. */
  queue: (setup: Project) => void
  /** Persist every pending edit now; resolves to the newest revision or null. */
  flush: () => Promise<Revision | null>
  /** Retry a failed write, resolving a concurrent edit first. */
  retry: () => Promise<Revision | null>
  /** Discard the local draft and adopt the newest head (user choice). */
  reload: () => Promise<Revision | null>
  /** Abandon local scheduling for a new model/route without writing. */
  forget: () => void
}

const IDLE: AutoSaveState = {
  phase: 'saved',
  error: '',
  dirty: false,
  conflict: false,
  conflicts: [],
}

function isConflict(message: string) {
  return /another revision was saved|changed by another tab|after you reviewed|impact changed/i.test(
    message,
  )
}

export function useAutoSave({
  projectId,
  baseId,
  baseline,
  enabled,
  onSaved,
  debounceMs = 350,
}: {
  projectId: string
  /** The head revision id the next write must use as its base. */
  baseId: string
  /** Serialized setup of that head, so an untouched draft is never re-saved. */
  baseline: string
  /** False for a locked replay, an archived model or a 3D preview. */
  enabled: boolean
  /** Receives the committed revision and the exact setup that was written. */
  onSaved: (revision: Revision, sent: Project, adopt?: boolean) => void
  debounceMs?: number
}): AutoSaver {
  const [state, setState] = useState<AutoSaveState>(IDLE)
  const base = useRef(baseId)
  const pending = useRef<Project | null>(null)
  const running = useRef<Promise<void> | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSaved = useRef<string | null>(null)
  // When a retry rebases the local delta onto a newer head, the callback must
  // still compare the form against the draft the engineer typed, not the merged
  // setup, so an untouched form adopts the merged result.
  const sentAs = useRef<Project | null>(null)
  const latestRevision = useRef<Revision | null>(null)
  const generation = useRef(0)
  const alive = useRef(true)
  // Queueing happens from an effect, so it must not read a stale render value.
  const phase = useRef<AutoSaveState>(IDLE)
  const baselineSetup = useRef(baseline)
  baselineSetup.current = baseline
  // The parent is the authority for the base id after a navigation or save.
  base.current = baseId
  const savedRef = useRef(onSaved)
  savedRef.current = onSaved

  const update = (next: Partial<AutoSaveState>) => {
    phase.current = { ...phase.current, ...next }
    if (alive.current) setState(phase.current)
  }

  function clearTimer() {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }

  async function write(setup: Project, gen: number, sent: Project = setup): Promise<Revision | null> {
    update({ phase: 'saving', error: '', dirty: true, conflict: false, conflicts: [] })
    try {
      const saved = await request<Revision>('/api/projects/' + projectId, 'PUT', {
        base: base.current,
        setup,
      })
      if (gen !== generation.current) return null
      lastSaved.current = JSON.stringify(saved.setup)
      latestRevision.current = saved
      base.current = saved.id
      savedRef.current(saved, sent)
      return saved
    } catch (error) {
      if (gen !== generation.current) return null
      const message = err(error)
      // Keep the unsent draft so the engineer never loses typed values.
      if (!pending.current) pending.current = setup
      update({
        phase: 'error',
        error: message,
        dirty: true,
        conflict: isConflict(message),
        conflicts: [],
      })
      return null
    }
  }

  function drain(): Promise<void> {
    if (running.current) {
      // A write is already using the head; queue behind it, then write whatever
      // arrived while it ran. This is the coalescing point, not a second writer.
      return running.current.then(() => (pending.current ? drain() : undefined))
    }
    if (!enabled) return Promise.resolve()
    const gen = generation.current
    const loop = (async () => {
      let current = pending.current
      while (current) {
        pending.current = null
        const sent = sentAs.current ?? current
        sentAs.current = null
        const saved = await write(current, gen, sent)
        if (!saved) break
        update({ phase: 'saved', error: '', dirty: false, conflict: false, conflicts: [] })
        current = pending.current
      }
    })().finally(() => {
      running.current = null
    })
    running.current = loop
    return loop
  }

  function schedule() {
    clearTimer()
    timer.current = setTimeout(() => {
      timer.current = null
      void drain()
    }, debounceMs)
  }

  function queue(setup: Project) {
    if (!enabled) return
    const serialized = JSON.stringify(setup)
    // An untouched draft is the head, not an edit: never append a redundant
    // revision just because an action flushed before the debounce elapsed.
    if (serialized === lastSaved.current || serialized === baselineSetup.current) return
    pending.current = setup
    update({ dirty: true, phase: phase.current.phase === 'error' ? 'error' : 'pending' })
    // A real conflict waits for an explicit retry; every other failure benefits
    // from the next committed edit retrying automatically.
    if (phase.current.phase === 'error' && phase.current.conflict) return
    schedule()
  }

  async function flush(): Promise<Revision | null> {
    clearTimer()
    await drain()
    // An edit committed in the same tick as the last response is still pending.
    if (pending.current) await drain()
    // A caller about to queue work must never proceed with the previous setup.
    if (pending.current || phase.current.phase === 'error') {
      throw new Error(phase.current.error || 'The current edits could not be saved.')
    }
    return latestRevision.current ?? null
  }

  async function head(): Promise<Revision> {
    const rows = await request<RevisionSummary[]>('/api/projects/' + projectId + '/revisions')
    if (!rows.length) throw new Error('The model has no current revision.')
    return request<Revision>('/api/revisions/' + rows[0].id)
  }

  function adopt(current: Revision, force = false) {
    pending.current = null
    lastSaved.current = JSON.stringify(current.setup)
    latestRevision.current = current
    base.current = current.id
    savedRef.current(current, current.setup, force)
    update({ phase: 'saved', error: '', dirty: false, conflict: false, conflicts: [] })
  }

  function baseSetup(): Record<string, unknown> {
    try {
      return JSON.parse(baselineSetup.current) as Record<string, unknown>
    } catch {
      return {}
    }
  }

  async function retry(): Promise<Revision | null> {
    clearTimer()
    const draft = pending.current
    update({ phase: 'saving', error: '', conflict: false, conflicts: [] })
    try {
      // Resolve the current head first: a lost response may already have
      // committed this exact setup, and another tab may have moved the head.
      const current = await head()
      if (draft && JSON.stringify(current.setup) === JSON.stringify(draft)) {
        adopt(current)
        return current
      }
      if (!draft) {
        // Nothing local is pending: the newest head is the truth.
        adopt(current)
        return current
      }
      // Rebase only the local delta onto the newest head. Resubmitting the whole
      // stale snapshot would revert every field the other window committed.
      const merged = reconcile(
        baseSetup(),
        current.setup as Record<string, unknown>,
        draft as unknown as Record<string, unknown>,
      )
      if (!merged.ok) {
        pending.current = draft
        update({
          phase: 'error',
          error:
            'Another window changed ' +
            merged.conflicts.join(', ') +
            ' at the same time. Reload that revision, or save this edit as a separate model.',
          dirty: true,
          conflict: true,
          conflicts: merged.conflicts,
        })
        return null
      }
      if (!merged.changed) {
        adopt(current)
        return current
      }
      pending.current = merged.setup as unknown as Project
      base.current = current.id
      sentAs.current = draft
      await drain()
      // The written setup contains remote fields the form did not show. Compare
      // against the local draft so an untouched form adopts the merged result.
      return latestRevision.current
    } catch (error) {
      update({
        phase: 'error',
        error: err(error),
        dirty: !!pending.current,
        conflict: false,
        conflicts: [],
      })
      return null
    }
  }

  async function reload(): Promise<Revision | null> {
    clearTimer()
    try {
      const current = await head()
      adopt(current, true)
      return current
    } catch (error) {
      update({
        phase: 'error',
        error: err(error),
        dirty: !!pending.current,
        conflict: false,
        conflicts: [],
      })
      return null
    }
  }

  function forget() {
    clearTimer()
    generation.current += 1
    pending.current = null
    sentAs.current = null
    lastSaved.current = null
    latestRevision.current = null
    base.current = baseId
    phase.current = IDLE
    setState(IDLE)
  }

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      clearTimer()
      // Leaving the model must not discard a committed-in-spirit edit: the
      // write continues, but no late response touches an unmounted form.
      if (pending.current) void drain()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    base.current = baseId
  }, [baseId])

  useEffect(() => {
    // A different model (or a replay) starts from a clean writer state.
    forget()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, enabled])

  return { state, queue, flush, retry, reload, forget }
}
