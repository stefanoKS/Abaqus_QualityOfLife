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
  Play,
} from 'lucide-react'
import { useTranslate } from '../../i18n'
import type { TranslationKey } from '../../i18n'
import type { StepStatus } from './workflowStates'

export const WORKFLOW_STEPS: { nameKey: TranslationKey; icon: typeof FileInput }[] = [
  { nameKey: 'workspace.step.import', icon: FileInput },
  { nameKey: 'workspace.step.components', icon: Boxes },
  { nameKey: 'workspace.step.materials', icon: Layers3 },
  { nameKey: 'workspace.step.contact', icon: Link2 },
  { nameKey: 'workspace.step.motion', icon: MoveVertical },
  { nameKey: 'workspace.step.mesh', icon: Grid2X2 },
  { nameKey: 'workspace.step.review', icon: Play },
  { nameKey: 'workspace.step.results', icon: Activity },
]

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
      {WORKFLOW_STEPS.map(({ nameKey, icon: Icon }, index) => {
        const status = states[index] ?? { state: 'incomplete' as const }
        const state = status.state
        const label = t(nameKey)
        const current = stage === index
        const reason = status.hint ? t(status.hint) : undefined
        return (
          <button
            key={nameKey}
            type="button"
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
