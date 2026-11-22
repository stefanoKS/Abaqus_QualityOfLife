import { Activity, AlertTriangle, Clock } from 'lucide-react'
import type { Job, Revision } from '../../api'
import { labelFrom, useI18n } from '../../i18n'
import { Badge } from '../../Dashboard'
import { progressOf, isStale } from './progress'

/**
 * Top-of-run status. Progress is a fraction of configured simulated time, never
 * a wall-clock estimate; 100% appears only after solver and extraction succeed.
 */
export function ProgressSummary({
  job,
  setup,
  now,
}: {
  job: Job
  setup: Revision['setup'] | null
  now: number
}) {
  const { t, formatDateTime } = useI18n()
  const progress = progressOf(job, setup)
  const stale = isStale(job, now)
  const extractionFailed = ['Failed', 'Cancelled'].includes(job.extraction)
  const last = job.heartbeat ?? job.started ?? job.created
  return (
    <section className="card run-progress" data-testid="run-progress" data-determinate={progress.determinate}>
      <div className="progress-head">
        <Activity aria-hidden="true" />
        <h2>{labelFrom(t, 'phase', job.phase)}</h2>
        <div className="spacer" />
        <Badge value={job.status} />
      </div>

      <div
        className={'progress-track' + (progress.determinate ? '' : ' indeterminate')}
        role="progressbar"
        aria-label={t('progress.simulatedProgress')}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress.determinate ? Math.round(progress.percent ?? 0) : undefined}
        data-indeterminate={progress.determinate ? 'false' : 'true'}
      >
        {progress.determinate && (
          <span style={{ width: Math.max(0, Math.min(100, progress.percent ?? 0)) + '%' }} />
        )}
      </div>
      <p className="progress-caption">
        {progress.complete
          ? t('progress.complete')
          : progress.determinate
            ? t('progress.simulated', { percent: Math.round(progress.percent ?? 0) })
            : t('progress.indeterminate')}
      </p>

      <ol className="progress-steps" data-testid="progress-steps">
        {progress.steps.map((step, index) => {
          const state = progress.complete
            ? 'complete'
            : index < progress.completed
              ? 'complete'
              : index === progress.active
                ? 'active'
                : 'pending'
          return (
            <li key={step.name} data-step={step.name} data-state={state}>
              <span>{step.name}</span>
              <small>{t(step.role === 'body' ? 'run.roleBody' : 'run.roleDoor')}</small>
              <strong>
                {state === 'complete'
                  ? t('progress.stepComplete')
                  : state === 'active'
                    ? t('progress.stepActive')
                    : t('progress.stepPending')}
              </strong>
            </li>
          )
        })}
      </ol>

      <dl className="progress-facts">
        <div>
          <dt>{t('diag.solver')}</dt>
          <dd>{labelFrom(t, 'state', job.solver)}</dd>
        </div>
        <div>
          <dt>{t('diag.extraction')}</dt>
          <dd>{labelFrom(t, 'state', job.extraction)}</dd>
        </div>
        <div>
          <dt>{t('diag.increment')}</dt>
          <dd>{job.increment ?? '—'}</dd>
        </div>
        <div>
          <dt>{t('diag.stepTime')}</dt>
          <dd>{typeof job.step_time === 'number' ? job.step_time.toFixed(4) + ' s' : '—'}</dd>
        </div>
        <div>
          <dt>{t('diag.lastUpdate')}</dt>
          <dd>{formatDateTime(last)}</dd>
        </div>
      </dl>

      {job.solver === 'Waiting for license' && (
        <p className="notice" data-testid="license-wait">
          {t('progress.licenseWait')}
        </p>
      )}
      {progress.awaitingExtraction && !extractionFailed && (
        <p className="notice" data-testid="awaiting-extraction">
          {t('progress.awaitingExtraction')}
        </p>
      )}
      {job.solver === 'Succeeded' && extractionFailed && (
        <p className="error-text" data-testid="extraction-failed">
          {t('progress.extractionFailed')}
        </p>
      )}
      {stale && (
        <p className="error-text" data-testid="stale-heartbeat" role="alert">
          <AlertTriangle aria-hidden="true" /> {t('progress.staleHeartbeat')}
        </p>
      )}
      {!stale && job.status !== 'Completed' && job.status !== 'Failed' && job.status !== 'Cancelled' && (
        <p className="field-hint">
          <Clock aria-hidden="true" /> {t('progress.noEta')}
        </p>
      )}
    </section>
  )
}
