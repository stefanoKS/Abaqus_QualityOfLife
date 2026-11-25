import { FileText, LoaderCircle, Play, RefreshCw, ShieldCheck } from 'lucide-react'
import type { Job } from '../../api'
import { artifact } from '../../api'
import { useI18n, labelFrom, type TranslationKey } from '../../i18n'

/**
 * Prepare and Submit are one compact group at the top of the Results
 * properties, available throughout editable 2D setup. The server's
 * action-specific readiness decides enablement; the browser adds only unsaved
 * drafts and in-flight operations. Prepare never enqueues a mesh and Submit
 * uses the exact prepared deck.
 */
export function AnalysisActions({
  locked,
  archived,
  pendingDeck,
  preparing,
  submitting,
  deck,
  deckReady,
  deckIssue,
  prepareReason,
  submitReason,
  runName,
  setRunName,
  cpus,
  setCpus,
  outputDir,
  setOutputDir,
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
  /** Actual deck state: failed/cancelled/preparing/superseded/stale fixture. */
  deckIssue: { code: string; detail?: string; phase?: string } | null
  prepareReason: string
  submitReason: string
  runName: string
  setRunName: (value: string) => void
  cpus: number
  setCpus: (value: number) => void
  /** Captured output folder for the portable result file (optional). */
  outputDir: string
  setOutputDir: (value: string) => void
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
          {deckReady && deck ? (
            <div className="action-deck build-info" data-testid="deck-status" data-state="ready">
              <strong>{t('mesh.inputReady')}</strong>
              <span className="action-links">
                <a href={artifact(deck.id, 'analysis.inp')} target="_blank" rel="noreferrer">
                  <FileText /> {t('mesh.inspectDeck')}
                </a>
                <a href={artifact(deck.id, 'analysis.inp')} download>
                  {t('actions.downloadDeck')}
                </a>
              </span>
            </div>
          ) : (
            <div
              className="action-deck build-info"
              data-testid="deck-status"
              data-state={deckIssue?.code ?? 'mesh.deckMissing'}
            >
              <strong>{t((deckIssue?.code ?? 'mesh.deckMissing') as TranslationKey)}</strong>
              {deckIssue?.detail && (
                <small className="deck-diagnostic" data-testid="deck-diagnostic">
                  {deckIssue.detail}
                </small>
              )}
              {deckIssue?.phase && (
                <small data-testid="deck-failed-stage">
                  {t('mesh.deckFailedStage', { stage: deckIssue.phase })}
                </small>
              )}
              <small data-testid="deck-hint">
                {t(
                  (deckIssue?.code === 'mesh.deckStaleFixture'
                    ? 'mesh.deckStaleFixtureHint'
                    : deckIssue?.code === 'mesh.deckFailed' ||
                        deckIssue?.code === 'mesh.deckCancelled'
                      ? 'mesh.deckFailureHint'
                      : deckIssue?.code === 'mesh.deckMissing'
                        ? 'mesh.deckMissingHint'
                        : deckIssue?.code === 'mesh.deckPreparing'
                          ? 'mesh.deckPreparingHint'
                          : 'mesh.deckStaleHint') as TranslationKey,
                )}
              </small>
              {deck && (
                <a className="deck-diagnostics" href={'#diagnostics/' + deck.id}>
                  {t('mesh.deckOpenDiagnostics')}
                </a>
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
          {activeRun?.result_file && (
            <a
              className="action-result-file"
              data-testid="result-file"
              href={'file:///' + activeRun.result_file.replace(/\\/g, '/')}
              title={activeRun.result_file}
            >
              <FileText /> {activeRun.result_file.split(/[\\/]/).pop()}
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
          <label className="action-field action-output">
            {t('file.resultFolder')}
            <input
              data-testid="output-dir"
              value={outputDir}
              placeholder="C:\\results"
              onChange={(event) => setOutputDir(event.target.value)}
            />
            <small>{t('file.resultFolderHint')}</small>
          </label>
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
