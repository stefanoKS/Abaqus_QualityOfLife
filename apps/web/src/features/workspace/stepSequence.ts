/**
 * Browser mirror of the server's role-derived step sequence.
 *
 * The server remains authoritative: it derives and stores `analysis.mode` when
 * a revision is saved. This helper gives the Motion and Review panes the same
 * readable summary and blocker codes immediately, including for an unsaved
 * draft, so the user never sees a manual mode switch that could disagree.
 */
import type { Project } from '../../api'

export type StepMode = 'door_only' | 'body_then_door'

export type StepPlan = {
  mode: StepMode
  counts: { seal: number; moving_panel: number; vehicle_body: number; unassigned: number }
  findings: { code: string; count: number }[]
  steps: { id: string; name: string; role: 'door' | 'body' }[]
}

export function stepPlan(project: Project): StepPlan {
  const solid = new Set(project.faces.filter((face) => !face.cavity).map((face) => face.component))
  const curved = new Set(project.edges.map((edge) => edge.component))
  const participating = new Set([...solid, ...curved])
  const counts = { seal: 0, moving_panel: 0, vehicle_body: 0, unassigned: 0 }
  for (const component of project.components) {
    if (component.role === 'seal') {
      if (solid.has(component.id)) counts.seal += 1
    } else if (participating.has(component.id)) {
      counts[component.role] += 1
    }
  }
  const findings: StepPlan['findings'] = []
  if (counts.unassigned) findings.push({ code: 'components.unassigned', count: counts.unassigned })
  if (!counts.seal) findings.push({ code: 'components.no_seal', count: 0 })
  if (!counts.moving_panel) findings.push({ code: 'components.no_moving_panel', count: 0 })
  else if (counts.moving_panel > 1)
    findings.push({ code: 'components.duplicate_moving_panel', count: counts.moving_panel })
  if (counts.vehicle_body > 1)
    findings.push({ code: 'components.duplicate_moving_body', count: counts.vehicle_body })
  const mode: StepMode =
    counts.seal >= 1 &&
    counts.moving_panel === 1 &&
    counts.vehicle_body === 1 &&
    counts.unassigned === 0
      ? 'body_then_door'
      : 'door_only'
  const steps =
    mode === 'body_then_door'
      ? [
          { id: 'bodyseating', name: 'Body seating', role: 'body' as const },
          { id: 'closing', name: 'Closing', role: 'door' as const },
        ]
      : [{ id: 'closing', name: 'Closing', role: 'door' as const }]
  return { mode, counts, findings, steps }
}

export function motionDelta(stroke: number, angle: number): [number, number] {
  if (!Number.isFinite(stroke) || !Number.isFinite(angle) || stroke < 0) return [0, 0]
  const radians = (angle * Math.PI) / 180
  const clean = (value: number) => (Math.abs(value) < 1e-12 ? 0 : value)
  return [clean(stroke * Math.cos(radians)), clean(stroke * Math.sin(radians))]
}
