import { riskTone } from '@/utils/format'

/**
 * Small status pill.
 *
 * Pass `risk` for a water-safety badge (safe / moderate / unsafe), or `tone`
 * for a neutral colour. Colours come from `riskTone` so chart fills and badges
 * stay visually consistent.
 *
 * THREE FINISHES for a risk badge:
 *   (default)  pale tint + dark text — the flat chip used in lists and cards
 *   `button`   the same tint in a bordered control shape (reports readings list)
 *   `solid`    the SATURATED colour filled edge-to-edge with WHITE text. The
 *              Home page's verdict boxes use this: the box is the colour itself
 *              and only the word inside it is white.
 */
export default function Badge({ children, risk, tone = 'slate', button = false, solid = false, className = '' }) {
  if (risk) {
    const { badge, label } = riskTone(risk)
    // `solid` wins over `button`: a filled chip has no need for the bordered
    // control shape, so the two are mutually exclusive and the solid one is the
    // stronger instruction.
    const style = solid
      ? badge.replace('badge-', 'badge-solid-')
      : button
        ? badge.replace('badge-', 'badge-button-')
        : badge
    return <span className={`${style} ${className}`}>{children ?? label}</span>
  }

  const toneClasses = {
    slate: 'badge-slate',
    aqua: 'badge bg-aqua-100 text-aqua-800',
    safe: button ? 'badge-button-safe' : 'badge-safe',
    moderate: button ? 'badge-button-moderate' : 'badge-moderate',
    unsafe: button ? 'badge-button-unsafe' : 'badge-unsafe',
  }

  return (
    <span className={`badge ${toneClasses[tone] || toneClasses.slate} ${className}`}>{children}</span>
  )
}
