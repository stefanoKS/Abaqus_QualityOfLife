import { Box, ChevronDown, ChevronRight, Eye, EyeOff, Layers3, ScanLine } from 'lucide-react'
import type { Project } from '../../api'
import { useTranslate } from '../../i18n'
import type { SelectionMode } from '../../viewportModel'

export function AssemblyTree({
  project,
  currentComponent,
  chosen,
  hidden,
  expanded,
  onExpand,
  onVisibility,
  onPick,
}: {
  project: Project
  currentComponent?: string
  chosen?: string
  hidden: string[]
  expanded: string[]
  onExpand: (componentId: string) => void
  onVisibility: (componentId: string) => void
  onPick: (kind: SelectionMode, id: string, component: string) => void
}) {
  const t = useTranslate()
  return (
    <div className="tree">
      {project.components.map((component) => {
        const faces = project.faces.filter((f) => f.component === component.id)
        const edges = project.edges.filter((e) => e.component === component.id)
        const open = expanded.includes(component.id)
        return (
          <div key={component.id}>
            <div className={'tree-row ' + (currentComponent === component.id ? 'current' : '')}>
              <button
                type="button"
                aria-expanded={open}
                aria-label={t('workspace.expand', { name: component.name })}
                onClick={() => onExpand(component.id)}
              >
                {open ? <ChevronDown /> : <ChevronRight />}
              </button>
              <button
                type="button"
                className="tree-item"
                onClick={() => onPick('component', component.id, component.id)}
              >
                <Box />
                {component.name}
              </button>
              <button
                type="button"
                aria-pressed={hidden.includes(component.id)}
                aria-label={t('workspace.toggleVisibility', { name: component.name })}
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
