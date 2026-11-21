import {
  Activity,
  Boxes,
  CheckCircle2,
  ChevronRight,
  Circle,
  FileInput,
  Grid2X2,
  Layers3,
  Link2,
  Lock,
  MoveVertical,
  Pin,
  Play,
} from 'lucide-react'
import { useTranslate } from '../../i18n'
import type { TranslationKey } from '../../i18n'
import { STAGE_ORDER, type StageId } from './stages'
import type { StepStatus } from './workflowStates'

/** Labels follow `STAGE_ORDER`; the id is what routes and pickers use. */
export const STAGE_ICONS: Record<StageId, typeof FileInput> = {
  import: FileInput,
  components: Boxes,
  materials: Layers3,
  mesh: Grid2X2,
  mounting: Pin,
  contact: Link2,
  motion: MoveVertical,
  review: Play,
  results: Activity,
}

export const STAGE_LABELS: Record<StageId, TranslationKey> = {
  import: 'workspace.step.import',
  components: 'workspace.step.components',
  materials: 'workspace.step.materials',
  mesh: 'workspace.step.mesh',
  mounting: 'workspace.step.mounting',
  contact: 'workspace.step.contact',
  motion: 'workspace.step.motion',
  review: 'workspace.step.review',
  results: 'workspace.step.results',
}

export const WORKFLOW_STEPS = STAGE_ORDER.map((id) => ({
  id,
  nameKey: STAGE_LABELS[id],
  icon: STAGE_ICONS[id],
}))

export function WorkflowNavigation({
  stage,
  states,
  onSelect,
}: {
  stage: number
  states: StepStatus[]
  onSelect: (index: number) => void
}) {
  const t = useTranslate()
  return (
    <nav className="steps" aria-label={t('workspace.workflow')}>
      {WORKFLOW_STEPS.map(({ id, nameKey, icon: Icon }, index) => {
        const status = states[index] ?? { state: 'incomplete' as const }
        const state = status.state
        const label = t(nameKey)
        const current = stage === index
        const reason = status.hint ? t(status.hint) : undefined
        return (
          <button
            key={id}
            type="button"
            data-stage={id}
            className={current ? 'selected' : ''}
            data-state={state}
            data-current={current || undefined}
            aria-current={current ? 'step' : undefined}
            title={reason}
            onClick={() => onSelect(index)}
          >
            <Icon />
            <span className="step-name">{label}</span>
            <span className="step-state" aria-hidden="true">
              {state === 'complete' ? (
                <CheckCircle2 className="state-complete" />
              ) : state === 'blocked' ? (
                <Lock className="state-blocked" />
              ) : (
                <Circle className="state-open" />
              )}
            </span>
            {/* Text, not colour, carries the status for assistive technology. */}
            <span className="sr-only"> — {t(('state.step.' + state) as TranslationKey)}</span>
            {current && <ChevronRight />}
          </button>
        )
      })}
    </nav>
  )
}
