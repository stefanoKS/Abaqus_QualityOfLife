/**
 * One ordered list of workflow stages. Navigation, picking modes, mesh
 * visibility and panel rendering all read this table, so inserting a stage
 * cannot send the user to the wrong tool.
 */
export const STAGE_ORDER = [
  'import',
  'components',
  'materials',
  'mesh',
  'mounting',
  'contact',
  'motion',
  'review',
  'results',
] as const

export type StageId = (typeof STAGE_ORDER)[number]

export const STAGE: Record<StageId, number> = STAGE_ORDER.reduce(
  (index, id, position) => ({ ...index, [id]: position }),
  {} as Record<StageId, number>,
)

/** Stages that need the produced mesh on screen. */
export const MESH_STAGES: StageId[] = ['mesh', 'mounting', 'contact', 'review']

export function stageId(index: number): StageId {
  return STAGE_ORDER[index] ?? 'import'
}

/** The tool a stage expects, so entering it arms the matching picker. */
export function stageMode(id: StageId): 'component' | 'face' | 'edge' | 'node' {
  if (id === 'materials') return 'face'
  if (id === 'mesh') return 'edge'
  if (id === 'mounting') return 'node'
  return 'component'
}
