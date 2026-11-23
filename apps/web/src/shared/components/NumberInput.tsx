import { useEffect, useId, useState } from 'react'
import { useTranslate } from '../../i18n'
import { setFieldInvalid } from './draftGuard'

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
 * A required numeric field. Blank is invalid, not "unchanged": a cleared field
 * must never let Save quietly persist the previous value.
 */
function invalidValue(raw: string, min?: number, max?: number) {
  if (raw.trim() === '') return true
  const parsed = parse(raw)
  if (parsed === null) return true
  if (min !== undefined && parsed < min) return true
  if (max !== undefined && parsed > max) return true
  return false
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

  const invalid = invalidValue(draft, min, max)
  const message = !invalid
    ? ''
    : draft.trim() === ''
      ? t('validation.required')
      : parse(draft) === null
        ? t('materials.err.finite')
        : t('validation.outOfRange')

  // An invalid draft stays visible and blocks the write actions until it is
  // corrected or explicitly abandoned with Escape. Registration happens in the
  // change handler as well, so a blur followed immediately by a Save click
  // cannot race a render.
  useEffect(() => {
    setFieldInvalid(id, invalidValue(draft, min, max))
    return () => setFieldInvalid(id, false)
  }, [id, draft, min, max])
  const describedBy = [rangeHint ? id + '-hint' : '', message && touched ? id + '-error' : '']
    .filter(Boolean)
    .join(' ')

  function commit(raw: string) {
    setTouched(true)
    if (invalidValue(raw, min, max)) {
      // Keep the invalid text on screen so the engineer can see and correct it;
      // never revert to the saved value while Save could then appear to succeed.
      setFieldInvalid(id, true)
      return
    }
    setFieldInvalid(id, false)
    const next = parse(raw)
    if (next !== null && next !== value) onChange(next)
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
          onChange={(e) => {
            const raw = e.target.value
            setDraft(raw)
            // Synchronous registration: a click on Save in the same task must
            // already see the invalid state.
            setFieldInvalid(id, invalidValue(raw, min, max))
          }}
          onBlur={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commit(e.currentTarget.value)
            } else if (e.key === 'Escape') {
              setDraft(String(value))
              setFieldInvalid(id, false)
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
