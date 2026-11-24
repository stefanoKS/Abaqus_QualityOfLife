import { FileText, LoaderCircle, Play, RefreshCw, ShieldCheck } from 'lucide-react'
import type { Job } from '../../api'
import { artifact } from '../../api'
import { useI18n, labelFrom } from '../../i18n'

/**
 * Prepare and Submit are one compact group under the left workflow, available
 * throughout editable 2D setup. The server's action-specific readiness decides
 * enablement; the browser adds only unsaved drafts and in-flight operations.
 * Prepare never enqueues a mesh and Submit uses the exact prepared deck.
 */
export function AnalysisActions({
  locked,
  archived,
  pendingDeck,
  preparing,
  submitting,
  deck,
  deckReady,
  prepareReason,
  submitReason,
  runName,
  setRunName,
  cpus,
  setCpus,
  cap,
  activeRun,
  readinessError,
  readinessLoading,
  onRetry,
  onPrepare,
  onSubmit,
}: {
  locked?: Job
  archived: boolean
  pendingDeck: boolean
  preparing: boolean
  submitting: boolean
  deck: Job | null
  deckReady: boolean
  prepareReason: string
  submitReason: string
  runName: string
  setRunName: (value: string) => void
  cpus: number
  setCpus: (value: number) => void
  cap: Record<string, string>
  activeRun: Job | null
  readinessError: boolean
  readinessLoading: boolean
  onRetry: () => void
  onPrepare: () => void
  onSubmit: () => void
}) {
  const { t } = useI18n()
  const busy = pendingDeck || preparing || submitting
  return (
    <section
      className="action-group"
      data-testid="action-group"
      aria-label={t('actions.title')}
    >
      <div className="panel-title action-title">
        <FileText />
        {t('actions.title')}
        {readinessLoading && <LoaderCircle className="spin" aria-label={t('actions.checking')} />}
      </div>
      {readinessError && (
        <p className="action-error" role="alert" data-testid="readiness-error">
          {t('actions.readinessUnavailable')}{' '}
          <button type="button" className="link-button" onClick={onRetry}>
            <RefreshCw /> {t('actions.retry')}
          </button>
        </p>
      )}
      {locked ? (
        <div className="action-locked" data-testid="action-locked">
          <p>{t('actions.submittedSetup')}</p>
          <a className="button" href={'#diagnostics/' + locked.id}>
            {t('actions.openRun')}
          </a>
        </div>
      ) : (
        <fieldset disabled={archived} className="action-fields">
          <legend className="sr-only">{t('actions.title')}</legend>
          <button
            type="button"
            className="action-prepare"
            data-testid="prepare"
            disabled={!!prepareReason || pendingDeck || preparing || submitting}
            aria-describedby="prepare-reason prepare-note"
            title={prepareReason || undefined}
            onClick={onPrepare}
          >
            {pendingDeck || preparing ? <LoaderCircle className="spin" /> : <FileText />}
            {pendingDeck || preparing ? t('mesh.preparingDeck') : t('mesh.prepareDeck')}
          </button>
          <p
            className="action-reason"
            id="prepare-reason"
            data-testid="prepare-reason"
            aria-live="polite"
          >
            {prepareReason || t('actions.readyPrepare')}
          </p>
          <span id="prepare-note" className="sr-only">
            {t('review.prepareNeverMesh')}
          </span>
          {deck && (
            <div className="action-deck build-info" data-testid="deck-status">
              <strong>{deckReady ? t('mesh.inputReady') : t('mesh.deckStale')}</strong>
              {deckReady ? (
                <span className="action-links">
                  <a href={artifact(deck.id, 'analysis.inp')} target="_blank" rel="noreferrer">
                    <FileText /> {t('mesh.inspectDeck')}
                  </a>
                  <a href={artifact(deck.id, 'analysis.inp')} download>
                    {t('actions.downloadDeck')}
                  </a>
                </span>
              ) : (
                <small>{t('mesh.deckStaleHint')}</small>
              )}
            </div>
          )}

          <hr />
          <div className="action-subhead">
            <Play />
            {t('review.submitLicensed')}
            <span
              className="action-license"
              title={cap.abaqus === 'Configured' ? t('actions.licenseReady') : cap.abaqus || t('actions.checking')}
              aria-label={cap.abaqus === 'Configured' ? t('actions.licenseReady') : cap.abaqus || t('actions.checking')}
            >
              <ShieldCheck />
            </span>
          </div>
          <p className="action-reason" data-testid="submit-reason" aria-live="polite">
            {submitting ? t('actions.submitting') : submitReason || t('actions.readySubmit')}
          </p>
          {activeRun && (
            <a className="action-run" href={'#diagnostics/' + activeRun.id}>
              {t('actions.activeRun', {
                state: labelFrom(t, 'state', activeRun.status),
              })}
            </a>
          )}
          <div className="action-run-row">
            <label className="action-field">
              {t('review.runName')}
              <input
                maxLength={100}
                value={runName}
                onChange={(event) => setRunName(event.target.value)}
              />
            </label>
            <label className="action-field">
              {t('review.cpus')}
              <input
                type="number"
                min={1}
                max={32}
                step={1}
                value={Number.isFinite(cpus) ? cpus : ''}
                onChange={(event) => {
                  const value = Number(event.target.value)
                  if (event.target.value.trim() !== '' && Number.isFinite(value)) setCpus(value)
                }}
              />
            </label>
          </div>
          <button
            type="button"
            className="action-submit"
            data-testid="submit"
            disabled={!!submitReason || submitting || pendingDeck || preparing}
            aria-describedby="submit-reason"
            title={submitReason || undefined}
            onClick={onSubmit}
          >
            {submitting ? <LoaderCircle className="spin" /> : <Play />}
            {submitting ? t('actions.submitting') : t('review.submitLicensed')}
          </button>
        </fieldset>
      )}
    </section>
  )
}
