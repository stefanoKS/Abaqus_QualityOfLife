import { useEffect, useRef, useState } from 'react'
import { FileDown, FileInput, FolderOpen, Plus, RotateCcw } from 'lucide-react'
import { err, go, request, type Revision } from '../../api'
import { useI18n } from '../../i18n'

/**
 * The File entry point. A model and a result are portable documents opened from
 * a folder; the dashboard's project history remains readable during migration.
 * Nothing is copied into the database until a file is actually opened.
 */
export function FileBar({ notify }: { notify: (message: string) => void }) {
  const { t } = useI18n()
  const [mode, setMode] = useState<'model' | 'result' | null>(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [recent, setRecent] = useState<{ path: string; kind: 'model' | 'result' }[]>([])
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    try {
      const raw = localStorage.getItem('abaqus-qol.recent-files')
      if (raw) setRecent(JSON.parse(raw).slice(0, 5))
    } catch {
      // A private-mode browser simply has no recent files.
    }
  }, [])

  function remember(next: { path: string; kind: 'model' | 'result' }) {
    setRecent((current) => {
      const merged = [next, ...current.filter((row) => row.path !== next.path)].slice(0, 5)
      try {
        localStorage.setItem('abaqus-qol.recent-files', JSON.stringify(merged))
      } catch {
        // The list is a convenience, not state the model depends on.
      }
      return merged
    })
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
    </section>
  )
}
