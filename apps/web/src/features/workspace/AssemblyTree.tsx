import { useState } from 'react'
import { Box, Check, ChevronDown, ChevronRight, Eye, EyeOff, Layers3, Pencil, ScanLine, X } from 'lucide-react'
import type { Project } from '../../api'
import { useTranslate } from '../../i18n'
import type { SelectionMode } from '../../viewportModel'
import { componentLabel } from './componentLabel'

const ROLE_KEYS = {
  seal: 'role.seal',
  moving_panel: 'role.moving_panel',
  vehicle_body: 'role.vehicle_body',
  unassigned: 'role.unassigned',
} as const

export function AssemblyTree({
  project,
  currentComponent,
  chosen,
  hidden,
  expanded,
  onExpand,
  onVisibility,
  onPick,
  onRename,
}: {
  project: Project
  currentComponent?: string
  chosen?: string
  hidden: string[]
  expanded: string[]
  onExpand: (componentId: string) => void
  onVisibility: (componentId: string) => void
  onPick: (kind: SelectionMode, id: string, component: string) => void
  onRename: (componentId: string, alias: string) => void
}) {
  const t = useTranslate()
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  function start(component: Project['components'][number]) {
    setEditing(component.id)
    setDraft(component.alias ?? '')
  }
  function cancel() {
    setEditing(null)
    setDraft('')
  }
  function save(componentId: string) {
    const alias = draft.trim()
    if (!alias) return
    onRename(componentId, alias)
    cancel()
  }

  return (
    <div className="tree">
      {project.components.map((component) => {
        const faces = project.faces.filter((f) => f.component === component.id)
        const edges = project.edges.filter((e) => e.component === component.id)
        const open = expanded.includes(component.id)
        const label = componentLabel(component)
        return (
          <div key={component.id}>
            <div className={'tree-row ' + (currentComponent === component.id ? 'current' : '')}>
              <button
                type="button"
                aria-expanded={open}
                aria-label={t('workspace.expand', { name: label })}
                onClick={() => onExpand(component.id)}
              >
                {open ? <ChevronDown /> : <ChevronRight />}
              </button>
              {editing === component.id ? (
                <span className="tree-rename">
                  <input
                    autoFocus
                    value={draft}
                    maxLength={160}
                    aria-label={t('workspace.renameLabel', { name: label })}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        save(component.id)
                      } else if (e.key === 'Escape') {
                        e.preventDefault()
                        cancel()
                      }
                    }}
                  />
                  <button
                    type="button"
                    aria-label={t('workspace.renameSave', { name: label })}
                    title={t('workspace.renameSave', { name: label })}
                    disabled={!draft.trim()}
                    onClick={() => save(component.id)}
                  >
                    <Check />
                  </button>
                  <button
                    type="button"
                    aria-label={t('workspace.renameCancel', { name: label })}
                    title={t('workspace.renameCancel', { name: label })}
                    onClick={cancel}
                  >
                    <X />
                  </button>
                </span>
              ) : (
                <>
                  <button
                    type="button"
                    className="tree-item"
                    aria-label={label + ' · ' + t(ROLE_KEYS[component.role] ?? 'role.unassigned')}
                    onClick={() => onPick('component', component.id, component.id)}
                  >
                    <Box />
                    <span className="tree-label">{label}</span>
                    <span className="tree-role">
                      {t(ROLE_KEYS[component.role] ?? 'role.unassigned')}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="tree-rename-open"
                    aria-label={t('workspace.rename', { name: label })}
                    title={t('workspace.rename', { name: label })}
                    onClick={() => start(component)}
                  >
                    <Pencil />
                  </button>
                </>
              )}
              <button
                type="button"
                aria-pressed={hidden.includes(component.id)}
                aria-label={t('workspace.toggleVisibility', { name: label })}
                onClick={() => onVisibility(component.id)}
              >
                {hidden.includes(component.id) ? <EyeOff /> : <Eye />}
              </button>
            </div>
            {open && (
              <div className="children">
                {[
                  ...faces.map((f) => ({ id: f.id, name: f.name, kind: 'face' as const })),
                  ...edges.map((e) => ({ id: e.id, name: e.name, kind: 'edge' as const })),
                ].map((entity) => (
                  <button
                    key={entity.id}
                    type="button"
                    className={chosen === entity.id ? 'active' : ''}
                    onClick={() => onPick(entity.kind, entity.id, component.id)}
                  >
                    {entity.kind === 'face' ? <Layers3 /> : <ScanLine />}
                    {entity.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
