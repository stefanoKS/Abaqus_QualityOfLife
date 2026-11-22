/**
 * A component's user-facing label. ``name`` is the authoritative label from the
 * drawing/import; ``alias`` is an optional display name. IDs stay untouched, so
 * geometry, FE mappings and saved history never depend on either string.
 */
export function componentLabel(component: { name: string; alias?: string }) {
  return component.alias?.trim() || component.name
}
