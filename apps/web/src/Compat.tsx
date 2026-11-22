import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { AlertTriangle, RotateCw } from 'lucide-react'
import {
  EXPECTED_API,
  assess,
  compatibilityMessageKey,
  ownEntry,
  type Compatibility,
  type CompatibilityHealth,
} from './compatibility'
import { useI18n, type TranslationKey } from './i18n'

const CompatibilityContext = createContext<Compatibility>({
  ok: true,
  kind: 'ok',
  entry: '',
  release: '',
  api: EXPECTED_API,
})

/** Whether this tab may perform writes against the current API. */
export function useCompatibility(): Compatibility {
  return useContext(CompatibilityContext)
}

export function CompatibilityProvider({ children }: { children: ReactNode }) {
  const entry = useMemo(ownEntry, [])
  const [health, setHealth] = useState<CompatibilityHealth | null | undefined>(undefined)

  const check = useCallback(async () => {
    try {
      const response = await fetch('/api/health', { cache: 'no-store' })
      setHealth(response.ok ? ((await response.json()) as CompatibilityHealth) : null)
    } catch {
      setHealth(null)
    }
  }, [])

  useEffect(() => {
    void check()
    // A tab that was hidden while the service restarted must re-check before it
    // offers a write again; a cached tab is exactly the stale case.
    const onFocus = () => void check()
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    const timer = setInterval(check, 60000)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
      clearInterval(timer)
    }
  }, [check])

  const value = useMemo(() => {
    // Before the first answer, do not enable writes on an unverified pair.
    if (health === undefined) {
      return { ok: false, kind: 'unreachable' as const, entry, release: '', api: 0 }
    }
    return assess(health, entry)
  }, [health, entry])

  return (
    <CompatibilityContext.Provider value={value}>{children}</CompatibilityContext.Provider>
  )
}

export function CompatibilityBanner() {
  const compat = useCompatibility()
  const { t } = useI18n()
  if (compat.ok) return null
  return (
    <div className="compat-banner" role="alert" data-testid="compat-banner">
      <AlertTriangle aria-hidden="true" />
      <span>{t(compatibilityMessageKey(compat.kind) as TranslationKey)}</span>
      {compat.kind === 'stale-tab' || compat.kind === 'unreachable' ? (
        <button type="button" onClick={() => location.reload()}>
          <RotateCw aria-hidden="true" />
          {t('compat.reload')}
        </button>
      ) : null}
    </div>
  )
}
