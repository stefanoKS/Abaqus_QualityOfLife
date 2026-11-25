import { AlertTriangle, Info } from 'lucide-react'
import { useI18n } from '../../i18n'
import type { TranslationKey } from '../../i18n'
import type { AssemblyAssessment, AssemblyMotion } from './readiness'

/**
 * Measured assembled position for the Motion and Review stages.
 *
 * Every number comes from the geometry of the queued mesh. Travel past the
 * measured gap is reported as a necessary condition, never as proof that
 * contact happens: that is a solver result, not a placement measurement.
 */
export function AssemblyDiagnostics({
  assessment,
  dirty,
}: {
  assessment: AssemblyAssessment | null
  dirty: boolean
}) {
  const { t, formatNumber } = useI18n()
  const issue = assessment?.code
  const measured = !dirty && assessment ? assessment : null

  const roleName = (value: string | undefined) =>
    value === 'body' ? t('assembly.role.body') : t('assembly.role.door')

  /** The measured contact side is not limited to above/below on a curved return. */
  const sideName = (value: string | undefined) =>
    value === 'below'
      ? t('assembly.sideBelow')
      : value === 'left'
        ? t('assembly.sideLeft')
        : value === 'right'
          ? t('assembly.sideRight')
          : t('assembly.sideAbove')

  function issueText(): string {
    if (!issue) return ''
    const details = assessment?.details ?? {}
    return t(('assembly.issue.' + issue) as TranslationKey, {
      label: roleName(
        typeof details.label === 'string' ? details.label : undefined
      ),
      depth: typeof details.depth === 'number' ? formatNumber(details.depth) : '',
      side: sideName(typeof details.side === 'string' ? details.side : undefined),
    })
  }

  function motionRows(motion: AssemblyMotion) {
    const hold = motion.hold === true || motion.travel_mm === 0
    const dx = motion.direction[0] ?? 0
    const dy = motion.direction[1] ?? 0
    const direction = hold
      ? t('assembly.hold')
      : Math.abs(dy) >= Math.abs(dx)
        ? dy < 0
          ? t('assembly.directionDown')
          : t('assembly.directionUp')
        : dx < 0
          ? t('assembly.directionLeft')
          : t('assembly.directionRight')
    const angle =
      !hold && motion.angle_deg !== undefined
        ? ' · ' + formatNumber(motion.angle_deg) + '°'
        : ''
    return (
      <dl data-testid={'assembly-' + motion.role}>
        <div>
          <dt>{t('assembly.clearance')}</dt>
          <dd>{formatNumber(motion.clearance_mm)} mm</dd>
        </div>
        <div>
          <dt>{t('assembly.mountedSide')}</dt>
          <dd>{sideName(motion.side)}</dd>
        </div>
        <div>
          <dt>{t('assembly.offset')}</dt>
          <dd>{formatNumber(motion.initial_offset_mm)} mm</dd>
        </div>
        <div>
          <dt>{t('assembly.travel')}</dt>
          <dd>
            {formatNumber(motion.travel_mm)} mm · {direction}
            {angle}
          </dd>
        </div>
        <div>
          <dt>{t('assembly.reachesGap')}</dt>
          <dd>
            {hold
              ? t('assembly.hold')
              : motion.reaches_initial_gap
                ? t('assembly.yes')
                : t('assembly.no')}
          </dd>
        </div>
      </dl>
    )
  }

  const shortfalls = [measured?.door, measured?.body].filter(
    (motion): motion is AssemblyMotion =>
      !!motion && motion.hold !== true && motion.travel_mm !== 0 && !motion.reaches_initial_gap
  )

  return (
    <section
      className="assembly-diagnostics"
      data-testid="assembly-diagnostics"
      data-state={
        dirty
          ? 'stale'
          : issue
            ? 'invalid'
            : assessment?.door || assessment?.body
              ? 'measured'
              : assessment?.error
                ? 'unavailable'
                : 'unmeasured'
      }
    >
      <h3>
        <Info />
        {t('assembly.title')}
      </h3>
      {dirty && (
        <p className="notice" data-testid="assembly-stale">
          {t('assembly.saveToRefresh')}
        </p>
      )}
      {!dirty && issue && (
        <p className="error-text" role="alert" data-testid="assembly-issue">
          <AlertTriangle />
          {issueText()}
        </p>
      )}
      {!dirty && !issue && assessment?.error && (
        <p className="error-text" role="alert" data-testid="assembly-unavailable">
          {assessment.error}
        </p>
      )}
      {!dirty && !assessment && (
        <p className="notice" data-testid="assembly-needs-mesh">
          {t('assembly.needsMesh')}
        </p>
      )}
      {measured?.door && (
        <>
          <h4>{t('assembly.role.door')}</h4>
          {motionRows(measured.door)}
        </>
      )}
      {measured?.body && (
        <>
          <h4>{t('assembly.role.body')}</h4>
          {motionRows(measured.body)}
        </>
      )}
      {shortfalls.map((motion) => (
        <p className="notice" key={motion.role} data-testid={'assembly-short-' + motion.role}>
          {t('assembly.gapNotReached', {
            label: roleName(motion.role),
            travel: formatNumber(Math.abs(motion.travel_mm)),
            gap: formatNumber(motion.clearance_mm),
          })}
        </p>
      ))}
      {measured &&
        (measured.door?.reaches_initial_gap || measured.body?.reaches_initial_gap) && (
          <p className="quality-note subtle" data-testid="assembly-contact-caveat">
            {t('assembly.contactNotGuaranteed')}
          </p>
        )}
    </section>
  )
}
