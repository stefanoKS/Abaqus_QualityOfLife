import { useEffect, useRef, useState } from 'react'
import { FileDown, FileInput, FolderOpen, Plus, RotateCcw, XCircle } from 'lucide-react'
import {
  activeDocument,
  closeActiveDocument,
  err,
  go,
  recentFiles,
  rememberRecentFile,
  request,
  type ActiveDocument,
  type Revision,
  type RevisionSummary,
} from '../../api'
import { useI18n } from '../../i18n'

/**
 * The File entry point. A model and a result are portable documents opened from
 * a folder; the dashboard's project history remains readable during migration.
 * Nothing is copied into the database until a file is actually opened.
 */
export function FileBar({
  notify,
  onChanged,
}: {
  notify: (message: string) => void
  onChanged?: () => void
}) {
  const { t } = useI18n()
  const [mode, setMode] = useState<'model' | 'result' | null>(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [recent, setRecent] = useState<{ path: string; kind: 'model' | 'result' }[]>([])
  // The tab's open document, and the pending Close decision when the file on
  // disk would fall behind the working head.
  const [active, setActive] = useState<ActiveDocument | null>(() => activeDocument())
  const [closing, setClosing] = useState<{ document: ActiveDocument; head: Revision } | null>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setRecent(recentFiles())
    // The document session can change in the Workspace while this panel is
    // mounted; re-read it when the dashboard regains focus or a poll lands.
    const sync = () => {
      setActive(activeDocument())
      setRecent(recentFiles())
    }
    window.addEventListener('focus', sync)
    const timer = window.setInterval(sync, 1500)
    return () => {
      window.removeEventListener('focus', sync)
      window.clearInterval(timer)
    }
  }, [])

  async function headRevision(project: string): Promise<Revision> {
    const rows = await request<RevisionSummary[]>('/api/projects/' + project + '/revisions')
    if (!rows.length) throw new Error(t('file.noRevision'))
    return request<Revision>('/api/revisions/' + rows[0].id)
  }

  function finishClose(document: ActiveDocument) {
    closeActiveDocument(document.project)
    setActive(null)
    setClosing(null)
    notify(t('file.closed', { name: document.name }))
    onChanged?.()
    go('dashboard')
  }

  /**
   * Close the tab's document. An untitled document keeps its working head in
   * the file-document owner, so nothing is lost; a document whose file is
   * behind the working head asks before the disk copy is abandoned.
   */
  async function closeModel() {
    const document = active
    if (!document) return
    if (!document.path) {
      finishClose(document)
      return
    }
    try {
      const head = await headRevision(document.project)
      if (head.id === document.fileRevision && !document.dirty) {
        finishClose(document)
        return
      }
      setClosing({ document, head })
    } catch (error) {
      notify(err(error))
    }
  }

  /** Wait until the working head stops moving (an in-flight autosave landed). */
  async function settleHead(project: string, revision: Revision) {
    let current = revision
    let stable = 0
    for (let tick = 0; tick < 24; tick += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 250))
      const next = await headRevision(project)
      if (next.id !== current.id) {
        current = next
        stable = 0
        continue
      }
      stable += 1
      if (stable >= 2) break
    }
    return current
  }

  async function saveAndClose() {
    if (!closing) return
    const { document } = closing
    setBusy(true)
    try {
      // Commit every pending edit first, then package the revision that was
      // actually written. If a working-head write lands while packaging, the
      // file is written again so it can never trail the model it describes.
      let revision = await settleHead(document.project, closing.head)
      let sha = document.sha
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const written = await request<{ path: string; sha256: string }>(
          '/api/files/model/save',
          'POST',
          {
            revision: revision.id,
            path: document.path,
            base_sha: sha || undefined,
          },
        )
        sha = written.sha256
        const next = await settleHead(document.project, revision)
        if (next.id === revision.id) break
        revision = next
      }
      finishClose(document)
    } catch (error) {
      // The document stays open with its draft; nothing was discarded.
      notify(err(error))
    } finally {
      setBusy(false)
    }
  }

  function remember(next: { path: string; kind: 'model' | 'result' }) {
    setRecent(rememberRecentFile(next))
  }

  async function browse(next: 'model' | 'result') {
    try {
      const picked = await request<{ path: string }>(
        '/api/files/pick?mode=file&title=' +
          encodeURIComponent(
            next === 'model' ? t('file.chooseModel') : t('file.chooseResult'),
          ),
      )
      if (picked.path) setPath(picked.path)
    } catch (error) {
      notify(err(error))
    }
  }

  async function open(next: 'model' | 'result') {
    if (!path.trim() || busy) return
    setBusy(true)
    try {
      if (next === 'model') {
        const opened = await request<{ revision: Revision; path: string; sha256: string }>(
          '/api/files/model/open-info',
          'POST',
          { path: path.trim() },
        )
        remember({ path: path.trim(), kind: 'model' })
        try {
          localStorage.setItem(
            'model-file:' + opened.revision.project,
            JSON.stringify({ path: opened.path, sha: opened.sha256 }),
          )
        } catch {
          // The pathname is still shown for this session.
        }
        go('workspace/' + opened.revision.id)
      } else {
        const job = await request<{ id: string }>('/api/files/result/open', 'POST', {
          path: path.trim(),
        })
        remember({ path: path.trim(), kind: 'result' })
        go('results/' + job.id)
      }
    } catch (error) {
      notify(err(error))
    } finally {
      setBusy(false)
    }
  }

  async function newModel() {
    if (busy) return
    setBusy(true)
    try {
      const revision = await request<Revision>('/api/projects', 'POST', {
        name: t('file.untitled'),
      })
      go('workspace/' + revision.id)
    } catch (error) {
      notify(err(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="file-bar card" data-testid="file-bar">
      <div className="panel-title">
        <FileInput />
        {t('file.title')}
        <div className="spacer" />
        <button className="primary" onClick={newModel} disabled={busy} data-testid="file-new">
          <Plus />
          {t('file.new')}
        </button>
      </div>
      <div className="file-body">
        {active && (
          <div className="file-active" data-testid="file-active">
            <span>
              {t('file.activeDocument')}: <strong>{active.name}</strong>
              {' — '}
              {active.path || t('file.notSaved')}
            </span>
            <button
              type="button"
              data-testid="file-close"
              disabled={busy}
              onClick={() => void closeModel()}
            >
              <XCircle />
              {t('file.close')}
            </button>
          </div>
        )}
        <div className="row-actions">
          <button
            type="button"
            data-testid="file-open-model"
            onClick={() => setMode(mode === 'model' ? null : 'model')}
          >
            <FolderOpen />
            {t('file.openModel')}
          </button>
          <button
            type="button"
            data-testid="file-open-result"
            onClick={() => setMode(mode === 'result' ? null : 'result')}
          >
            <FileDown />
            {t('file.openResult')}
          </button>
        </div>
        {mode && (
          <form
            className="file-open"
            onSubmit={(event) => {
              event.preventDefault()
              void open(mode)
            }}
          >
            <label>
              {mode === 'model' ? t('file.modelPath') : t('file.resultPath')}
              <input
                autoFocus
                ref={input}
                value={path}
                placeholder={mode === 'model' ? 'C:\\models\\seal.aqmodel' : 'C:\\results\\run.aqresult'}
                onChange={(event) => setPath(event.target.value)}
              />
            </label>
            <button type="button" onClick={() => void browse(mode)}>
              <FolderOpen /> {t('file.browse')}
            </button>
            <button type="submit" className="primary" disabled={busy || !path.trim()}>
              {t('file.open')}
            </button>
          </form>
        )}
        {recent.length > 0 && mode === null && (
          <div className="file-recent">
            <small>{t('file.recent')}</small>
            {recent.map((row) => (
              <button
                type="button"
                key={row.kind + row.path}
                onClick={() => {
                  setPath(row.path)
                  setMode(row.kind)
                }}
              >
                <RotateCcw />
                <span>{row.path}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {closing && (
        <div className="dialog-backdrop" data-testid="close-dialog-backdrop">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="close-dialog-title"
            className="dialog card"
            data-testid="close-dialog"
          >
            <h2 id="close-dialog-title">{t('file.closeTitle')}</h2>
            <p className="dialog-target">
              {t('file.closeUnsaved', {
                name: closing.document.name,
                path: closing.document.path,
              })}
            </p>
            <div className="dialog-actions">
              <button
                type="button"
                className="primary"
                data-testid="close-save"
                disabled={busy}
                onClick={() => void saveAndClose()}
              >
                {t('file.saveAndClose')}
              </button>
              <button
                type="button"
                data-testid="close-discard"
                disabled={busy}
                onClick={() => finishClose(closing.document)}
              >
                {t('file.closeWithoutSaving')}
              </button>
              <button
                type="button"
                data-testid="close-cancel"
                disabled={busy}
                onClick={() => setClosing(null)}
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
