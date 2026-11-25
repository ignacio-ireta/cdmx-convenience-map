// WCAG 2.x contrast ratio between two opaque sRGB colours (test-only helper).
// https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio

function channel(value: number) {
  const c = value / 255
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

export function relativeLuminance(hex: string) {
  const match = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!match) throw new Error(`Expected a #rrggbb colour, got ${hex}`)
  const n = Number.parseInt(match[1], 16)
  const r = channel((n >> 16) & 255)
  const g = channel((n >> 8) & 255)
  const b = channel(n & 255)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastRatio(foreground: string, background: string) {
  const [light, dark] = [relativeLuminance(foreground), relativeLuminance(background)].sort(
    (a, b) => b - a,
  )
  return (light + 0.05) / (dark + 0.05)
}

/** Euclidean distance in sRGB, a crude guard against near-duplicate inks. */
export function rgbDistance(a: string, b: string) {
  const rgb = (hex: string) => {
    const n = Number.parseInt(hex.slice(1), 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const [x, y] = [rgb(a), rgb(b)]
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2])
}
