import { useSyncExternalStore } from 'react'

/**
 * Tracks numeric fields whose visible draft is invalid.
 *
 * The draft stays in the input (it is never silently replaced by the last saved
 * value), and Save / Prepare / Submit must not proceed while any field is in
 * that state. The registry is module-wide because the fields live in several
 * child components and the actions live in the workspace header and Review.
 */
const invalid = new Set<string>()
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

export function setFieldInvalid(id: string, bad: boolean) {
  const had = invalid.has(id)
  if (bad && !had) {
    invalid.add(id)
    emit()
  } else if (!bad && had) {
    invalid.delete(id)
    emit()
  }
}

export function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function snapshot() {
  return invalid.size > 0
}

/** Synchronous check for action handlers; never read React state for safety. */
export function hasInvalidField() {
  return invalid.size > 0
}

export function useAnyInvalidField() {
  return useSyncExternalStore(subscribe, snapshot, snapshot)
}
