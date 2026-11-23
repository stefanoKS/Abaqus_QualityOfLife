/**
 * Abaqus QOL brand lockup.
 *
 * The mark is local, vector and scalable: a hollow seal section (jade ring with
 * its open foot) over a tangerine mounting foot. Red is reserved for errors, so
 * the mark never uses it. The wordmark is real text, not artwork, so it stays
 * crisp at every zoom and the accessible product name is always the visible one.
 */

export function BrandMark({ size = 40 }: { size?: number }) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 48 48"
      role="img"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M13.5 31.5C8.4 23.6 12.6 12.5 24 12.5s15.6 11.1 10.5 19"
        fill="none"
        stroke="var(--color-jade, #007C6E)"
        strokeWidth="4.6"
        strokeLinecap="round"
      />
      <path
        d="M12.4 32.2h23.2v3.1a3 3 0 0 1-3 3H15.4a3 3 0 0 1-3-3z"
        fill="var(--color-jade, #007C6E)"
      />
      <path
        d="M9 39.4h30"
        fill="none"
        stroke="var(--color-tangerine, #FF962C)"
        strokeWidth="4.4"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand-lockup">
      <BrandMark size={compact ? 30 : 38} />
      <span className="brand-divider" aria-hidden="true" />
      {!compact && <span className="brand-wordmark">Abaqus QOL</span>}
    </span>
  )
}

export default BrandLockup
