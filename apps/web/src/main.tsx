import { useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { FlaskConical, Languages, LayoutDashboard, Monitor, PanelTop, X } from 'lucide-react'
import { BrandLockup } from './Brand'
import Dashboard from './Dashboard'
import MaterialsPage from './MaterialsPage'
import Workspace from './Workspace'
import { RunView } from './RunView'
import { err, go, rememberModel, request, workspaceTarget, type Revision, type Summary, type Job } from './api'
import { I18nProvider, useI18n, type Language } from './i18n'
import { CompatibilityBanner, CompatibilityProvider } from './Compat'
import './theme/tokens.css'
import './style.css'

function LanguageButton() {
  const { t, lang, setLang } = useI18n()
  const next: Language = lang === 'ja' ? 'en' : 'ja'
  // The visible label names the destination language, so one activation is enough.
  const label = next === 'en' ? t('lang.en') : t('lang.ja')
  return (
    <button
      type="button"
      className="lang-button"
      lang={next === 'en' ? 'en' : 'ja'}
      aria-label={t('lang.switchTo', { language: label })}
      title={t('lang.switchTo', { language: label })}
      onClick={() => setLang(next)}
    >
      <Languages aria-hidden="true" />
      <span>{label}</span>
    </button>
  )
}

function App() {
  const { t } = useI18n()
  // A cold start with no route opens the Dashboard, the file entry point.
  const [route, setRoute] = useState(location.hash.slice(1) || 'dashboard'),
    [rev, setRev] = useState<Revision | null>(null),
    [job, setJob] = useState<Job | undefined>()
  const [message, toast] = useState(''),
    [loadingError, setError] = useState('')
  const notify = useCallback((s: string) => toast(s), [])
  useEffect(() => {
    const handler = () => {
      setRoute(location.hash.slice(1))
      toast('')
    }
    window.addEventListener('hashchange', handler)
    window.addEventListener('abaqus-qol:route', handler)
    return () => {
      window.removeEventListener('hashchange', handler)
      window.removeEventListener('abaqus-qol:route', handler)
    }
  }, [])
  const [view, id] = route.split('/')
  useEffect(() => {
    const ac = new AbortController()
    async function open() {
      setRev(null)
      setJob(undefined)
      setError('')
      if (['dashboard', 'diagnostics', 'results', 'materials'].includes(view)) return
      let rid = id
      if (view === 'setup') {
        const j = await request<Job>('/api/jobs/' + id, 'GET', undefined, ac.signal)
        rid = j.revision
        setJob(j)
      } else if (!rid) {
        // A workspace route without a model is not an invitation to pick one.
        go('dashboard')
        return
      }
      const r = await request<Revision>('/api/revisions/' + rid, 'GET', undefined, ac.signal)
      // Only an explicitly opened, editable model becomes the Workspace target.
      if (view !== 'setup') rememberModel(r.project)
      setRev(r)
    }
    void open().catch((e) => {
      if (!ac.signal.aborted) {
        setError(err(e) + (id ? ' · ' + id : ''))
      }
    })
    return () => ac.abort()
  }, [view, id])
  function dashboard() {
    go('dashboard')
    toast('')
  }
  async function workspace() {
    try {
      const ps = await request<Summary[]>('/api/projects')
      // The tab's own document first, then the last explicitly opened model.
      // Never silently open whichever model happens to sort first, and never
      // reopen a document this tab deliberately closed. A tab document is
      // remembered by its working head, so match either identity.
      const target = workspaceTarget()
      const found = target
        ? ps.find((p) => p.id === target || p.revision === target)
        : undefined
      go(found ? 'workspace/' + found.revision : 'dashboard')
    } catch (e) {
      notify(err(e))
    }
  }
  return (
    <>
      <header className="topbar">
        <button className="brand" onClick={workspace} aria-label={t('nav.brandAria')}>
          {/* Local vector mark + text wordmark: crisp at every zoom, and the
              accessible product name is the visible one. */}
          <BrandLockup />
          <span className="brand-name sr-only">{t('app.name')}</span>
        </button>
        <div className="nav-separator" />
        {/* The file entry point comes first: Dashboard owns New/Open/Close, and
            Workspace is reached from an open document. */}
        <nav aria-label={t('nav.main')}>
          <button
            className={
              view === 'dashboard' || view === 'diagnostics' || view === 'results' ? 'here' : ''
            }
            onClick={dashboard}
          >
            <LayoutDashboard />
            {t('nav.dashboard')}
          </button>
          <button
            className={!['dashboard', 'diagnostics', 'results', 'materials'].includes(view) ? 'here' : ''}
            onClick={workspace}
          >
            <PanelTop />
            {t('nav.workspace')}
          </button>
          <button className={view === 'materials' ? 'here' : ''} onClick={() => go('materials')}>
            <FlaskConical />
            {t('nav.materials')}
          </button>
        </nav>
        <span className="spacer" />
        <span className="local">
          <Monitor />
          {t('nav.localSession')}
        </span>
        <LanguageButton />
      </header>
      <CompatibilityBanner />
      {view === 'materials' ? (
        <MaterialsPage notify={notify} />
      ) : view === 'dashboard' ? (
        <Dashboard notify={notify} />
      ) : view === 'diagnostics' || view === 'results' ? (
        <RunView key={route} id={id} resultView={view === 'results'} notify={notify} />
      ) : rev ? (
        <Workspace key={route + rev.id} initial={rev} locked={job} notify={notify} />
      ) : (
        <main className="page">
          <p role="alert" className={loadingError ? 'error-text' : undefined}>
            {loadingError || t('common.openingProject')}
          </p>
          {loadingError && (
            <button onClick={() => go('dashboard')}>{t('workspace.backToProjects')}</button>
          )}
        </main>
      )}
      {message && (
        <div role="alert" className="toast">
          {message}
          <button aria-label={t('nav.dismiss')} onClick={() => toast('')}>
            <X />
          </button>
        </div>
      )}
    </>
  )
}
createRoot(document.getElementById('root')!).render(
  <I18nProvider>
    <CompatibilityProvider>
      <App />
    </CompatibilityProvider>
  </I18nProvider>,
)
