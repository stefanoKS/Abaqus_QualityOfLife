import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import type { Project } from '../../api'
import { useI18n } from '../../i18n'
import type { TranslationKey } from '../../i18n'
import type { MeshQuality } from './meshQuality'

export function MeshReview({
  quality,
  project,
  clearance,
}: {
  quality: MeshQuality
  project: Project
  clearance: number | null
}) {
  const { t, formatNumber } = useI18n()
  const warnings: string[] = []
  if (quality.worstEdgeRatio > 8)
    warnings.push(
      t('mesh.qualityWarning') + ' — max/min edge ratio ' + quality.worstEdgeRatio.toFixed(2),
    )
  const beyond = clearance === null ? null : Math.max(0, -project.motion.travel - clearance)
  // Every element belongs to exactly one component; included rows must add up to
  // the mesh total, so an excluded or missing component cannot hide elements.
  const includedTotal = quality.components.reduce(
    (sum, row) => sum + (row.included ? row.count : 0),
    0,
  )
  return (
    <div className="quality-summary">
      <h3>
        <CheckCircle2 className="state-complete" />
        {t('mesh.quality')}
      </h3>
      <dl>
        <div>
          <dt>{t('mesh.nodes')}</dt>
          <dd>{quality.nodes.toLocaleString()}</dd>
        </div>
        <div>
          <dt>{t('mesh.elements')}</dt>
          <dd>{quality.elements.toLocaleString()}</dd>
        </div>
        {quality.byType.map((row) => (
          <div key={row.type}>
            <dt>{row.type}</dt>
            <dd>{row.count.toLocaleString()}</dd>
          </div>
        ))}
        <div>
          <dt>{t('mesh.minEdge')}</dt>
          <dd>{formatNumber(quality.shortestEdge)}</dd>
        </div>
        <div>
          <dt>{t('mesh.maxEdge')}</dt>
          <dd>{formatNumber(quality.longestEdge)}</dd>
        </div>
        <div>
          <dt>max / min edge ratio</dt>
          <dd>
            {formatNumber(quality.worstEdgeRatio, 2)} : 1
            {quality.worstElement ? ' · #' + quality.worstElement : ''}
          </dd>
        </div>
        {clearance !== null && (
          <>
            <div>
              <dt>{t('mesh.initialClearance')}</dt>
              <dd>{formatNumber(clearance)} mm</dd>
            </div>
            <div>
              <dt>{t('mesh.prescribedTravel')}</dt>
              <dd>{formatNumber(project.motion.travel)} mm</dd>
            </div>
            <div>
              <dt>
                {t('mesh.travelBeyondGap')} ({t('mesh.geometric')})
              </dt>
              <dd>{formatNumber(beyond ?? 0)} mm</dd>
            </div>
          </>
        )}
      </dl>
      <h3>{t('mesh.components')}</h3>
      <div className="mesh-components" data-testid="mesh-components">
        {quality.components.map((row) => {
          const excluded = row.role === 'vehicle_body' && !row.included
          const status = excluded ? 'excluded' : row.count > 0 ? 'included' : 'notMeshed'
          const role =
            row.role === 'moving_panel'
              ? t('mesh.role.door')
              : row.role === 'vehicle_body'
                ? t('mesh.role.body')
                : row.role === 'seal'
                  ? t('mesh.role.seal')
                  : t('mesh.role.unassigned')
          return (
            <section
              key={row.id}
              className="mesh-component"
              data-component={row.id}
              data-included={row.included}
              data-status={status}
            >
              <header>
                <strong>{row.name}</strong>
                <span className={'badge ' + (status === 'included' ? 'good' : '')}>
                  {t(('mesh.component.' + status) as TranslationKey)}
                </span>
              </header>
              <dl>
                <div>
                  <dt>{t('mesh.component.role')}</dt>
                  <dd>{role}</dd>
                </div>
                <div>
                  <dt>{t('mesh.component.type')}</dt>
                  <dd>{row.elementType || t('mesh.notApplicable')}</dd>
                </div>
                <div>
                  <dt>{t('mesh.component.count')}</dt>
                  <dd>{row.count.toLocaleString()}</dd>
                </div>
              </dl>
              <small>
                {t(('mesh.component.' + status + 'Detail') as TranslationKey, {
                  count: row.count,
                })}
              </small>
            </section>
          )
        })}
        <p className="mesh-included-total" data-testid="included-total">
          {t('mesh.includedTotal', {
            included: includedTotal.toLocaleString(),
            total: quality.elements.toLocaleString(),
          })}
        </p>
        {includedTotal !== quality.elements && (
          <p className="error-text" role="alert">
            {t('mesh.includedMismatch')}
          </p>
        )}
      </div>
      {quality.regions.length > 0 && (
        <>
          <h3>{t('mesh.regions')}</h3>
          <dl>
            {quality.regions.map((region) => (
              <div key={region.id}>
                <dt>{region.name}</dt>
                <dd>{region.count.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <p className="quality-note">
        <Info />
        {t('mesh.qualityOk')}
      </p>
      {warnings.map((warning) => (
        <p key={warning} className="error-text quality-warning">
          <AlertTriangle />
          {warning}
        </p>
      ))}
      <p className="quality-note subtle">{t('mesh.notReadyHint')}</p>
    </div>
  )
}
