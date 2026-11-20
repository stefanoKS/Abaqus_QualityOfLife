import { useEffect, useId, useState } from 'react'
import { useTranslate } from '../../i18n'

export interface NumberInputProps {
  label: string
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  step?: string
  /** Rendered next to the field; engineering values are never localized. */
  unit?: string
  /** Explains the accepted range for accessible descriptions. */
  rangeHint?: string
  disabled?: boolean
}

function parse(raw: string): number | null {
  if (!raw.trim()) return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

/**
 * Draft-then-commit numeric field.
 *
 * Editing is local so a partially typed value never reaches the saved setup, and
 * the input is not remounted when the committed value changes (the previous
 * `key={value}` + `defaultValue` approach silently reverted in-progress typing
 * and reset focus). Enter or blur commits a valid value; Escape restores it.
 */
export function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step = 'any',
  unit,
  rangeHint,
  disabled,
}: NumberInputProps) {
  const id = useId()
  const t = useTranslate()
  const [draft, setDraft] = useState(() => String(value))
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    setDraft(String(value))
  }, [value])

  const parsed = parse(draft)
  const outsideRange =
    parsed !== null &&
    ((min !== undefined && parsed < min) || (max !== undefined && parsed > max))
  const invalid = (draft.trim() !== '' && parsed === null) || outsideRange
  const message = invalid ? t('materials.err.finite') : ''
  const describedBy = [rangeHint ? id + '-hint' : '', message && touched ? id + '-error' : '']
    .filter(Boolean)
    .join(' ')

  function commit(raw: string) {
    setTouched(true)
    const next = parse(raw)
    if (next === null || (min !== undefined && next < min) || (max !== undefined && next > max)) {
      setDraft(String(value))
      return
    }
    if (next !== value) onChange(next)
  }

  return (
    <label htmlFor={id}>
      {label}
      <span className="number-field">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          min={min}
          max={max}
          disabled={disabled}
          value={draft}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy || undefined}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commit(e.currentTarget.value)
            } else if (e.key === 'Escape') {
              setDraft(String(value))
              setTouched(false)
            }
          }}
        />
        {unit && <span className="number-unit">{unit}</span>}
      </span>
      {rangeHint && (
        <small id={id + '-hint'} className="field-hint">
          {rangeHint}
        </small>
      )}
      {touched && message && (
        <small id={id + '-error'} className="field-error" role="alert">
          {message}
        </small>
      )}
    </label>
  )
}
