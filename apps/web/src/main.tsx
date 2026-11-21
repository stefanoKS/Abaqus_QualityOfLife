import { useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Languages, LayoutDashboard, Monitor, PanelTop, X } from 'lucide-react'
import logo from '../assets/logo.png'
import Dashboard from './Dashboard'
import Workspace from './Workspace'
import { RunView } from './RunView'
import { err, go, request, type Revision, type Summary, type Job } from './api'
import { I18nProvider, useI18n, type Language } from './i18n'
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
  const [route, setRoute] = useState(location.hash.slice(1)),
    [rev, setRev] = useState<Revision | null>(null),
    [job, setJob] = useState<Job | undefined>()
  const [message, toast] = useState(''),
    [loadingError, setError] = useState(''),
    [last, setLast] = useState('')
  const notify = useCallback((s: string) => toast(s), [])
  useEffect(() => {
    const handler = () => {
      setRoute(location.hash.slice(1))
      toast('')
    }
    window.addEventListener('hashchange', handler)
    return () => window.removeEventListener('hashchange', handler)
  }, [])
  const [view, id] = route.split('/')
  useEffect(() => {
    const ac = new AbortController()
    async function open() {
      setRev(null)
      setJob(undefined)
      setError('')
      if (['dashboard', 'diagnostics', 'results'].includes(view)) return
      let rid = id
      if (view === 'setup') {
        const j = await request<Job>('/api/jobs/' + id, 'GET', undefined, ac.signal)
        rid = j.revision
        setJob(j)
      } else if (!rid) {
        const projects = await request<Summary[]>('/api/projects', 'GET', undefined, ac.signal)
        rid = projects[0]?.revision
      }
      if (!rid) {
        go('dashboard')
        return
      }
      const r = await request<Revision>('/api/revisions/' + rid, 'GET', undefined, ac.signal)
      if (view !== 'setup') setLast(r.project)
      setRev(r)
    }
    void open().catch((e) => {
      if (!ac.signal.aborted) setError(err(e))
    })
    return () => ac.abort()
  }, [view, id])
  async function workspace() {
    try {
      const ps = await request<Summary[]>('/api/projects')
      const r = ps.find((p) => p.id === last) ?? ps[0]
      go(r ? 'workspace/' + r.revision : 'dashboard')
    } catch (e) {
      notify(err(e))
    }
  }
  return (
    <>
      <header className="topbar">
        <button className="brand" onClick={workspace} aria-label={t('nav.brandAria')}>
          {/* The supplied wordmark already reads "Abaqus QOL"; the hidden span
              keeps a single accessible product name for assistive technology. */}
          <img className="brand-logo" src={logo} alt="" aria-hidden="true" />
          <span className="brand-name sr-only">{t('app.name')}</span>
        </button>
        <div className="nav-separator" />
        <nav aria-label={t('nav.main')}>
          <button
            className={!['dashboard', 'diagnostics', 'results'].includes(view) ? 'here' : ''}
            onClick={workspace}
          >
            <PanelTop />
            {t('nav.workspace')}
          </button>
          <button
            className={
              view === 'dashboard' || view === 'diagnostics' || view === 'results' ? 'here' : ''
            }
            onClick={() => go('dashboard')}
          >
            <LayoutDashboard />
            {t('nav.dashboard')}
          </button>
        </nav>
        <span className="spacer" />
        <span className="local">
          <Monitor />
          {t('nav.localSession')}
        </span>
        <LanguageButton />
      </header>
      {view === 'dashboard' ? (
        <Dashboard notify={notify} />
      ) : view === 'diagnostics' || view === 'results' ? (
        <RunView key={route} id={id} resultView={view === 'results'} notify={notify} />
      ) : rev ? (
        <Workspace key={route + rev.id} initial={rev} locked={job} notify={notify} />
      ) : (
        <main className="page">{loadingError || t('common.openingProject')}</main>
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
    <App />
  </I18nProvider>,
)
