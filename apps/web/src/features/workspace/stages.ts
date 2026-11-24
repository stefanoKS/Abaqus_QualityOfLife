/**
 * One ordered list of setup stages. Navigation, picking modes, mesh
 * visibility and panel rendering all read this table, so inserting a stage
 * cannot send the user to the wrong tool.
 *
 * Prepare and Submit are not a stage any more: they live at the top of the
 * Results properties, one group, reachable before any artifact exists.
 * Historical numeric storage mapped 7 = Review/Run and 8 = Results; those
 * decodes are kept here so an existing tab or saved selection reopens
 * somewhere useful without shifting indexes.
 */
export const STAGE_ORDER = [
  'import',
  'components',
  'materials',
  'mesh',
  'mounting',
  'contact',
  'motion',
  'results',
] as const

export type StageId = (typeof STAGE_ORDER)[number]

export const STAGE: Record<StageId, number> = STAGE_ORDER.reduce(
  (index, id, position) => ({ ...index, [id]: position }),
  {} as Record<StageId, number>,
)

/** Stages that need the produced mesh on screen. */
export const MESH_STAGES: StageId[] = ['mesh', 'mounting', 'contact', 'motion']

/**
 * Decode a persisted stage. New values are stable IDs; old values were numeric
 * indexes. Index 7 used to be Review/Run and becomes Motion (where the
 * analysis settings now live); index 8 stays Results.
 */
export function decodeStage(value: string | null | undefined, fallback: StageId): StageId {
  if (value === null || value === undefined || value === '') return fallback
  if ((STAGE_ORDER as readonly string[]).includes(value)) return value as StageId
  const index = Number(value)
  if (!Number.isFinite(index)) return fallback
  if (index === 7) return 'motion'
  if (index === 8) return 'results'
  return STAGE_ORDER[index] ?? fallback
}

/** The tool a stage expects, so entering it arms the matching picker. */
export function stageMode(id: StageId): 'component' | 'face' | 'edge' | 'node' {
  // Components owns region selection and the partition target, so a face pick
  // is the useful default there; the assembly tree still selects components.
  if (id === 'components' || id === 'materials') return 'face'
  if (id === 'mesh') return 'edge'
  if (id === 'mounting') return 'node'
  return 'component'
}
