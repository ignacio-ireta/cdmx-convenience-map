import { LEGEND_STEPS } from '../constants'
import { scoreFigure } from '../lib/format'

const CLASSES = [...LEGEND_STEPS].reverse()
const TICKS = [...CLASSES.map((step) => step.from), 100]

/**
 * The score ramp as a ruled bar drawn to scale: each class is as wide as the
 * range of scores it covers, with a tick at every class break. The classes are
 * stepped, not blended, because that is how the map is coloured.
 *
 * `score`, when given, puts a pointer on the bar at the selected area's score.
 */
export function ScoreLegend({
  metricLabel,
  score,
  selectedLabel,
}: {
  metricLabel: string
  score: number | null
  selectedLabel?: string
}) {
  const pointer = score == null ? null : Math.max(0, Math.min(100, score))

  return (
    <div
      className="legend"
      role="group"
      aria-label={`Legend: ${metricLabel} score, 0 to 100, in ${CLASSES.length} colour classes`}
    >
      <div className="legend-title">
        <span>Score · {metricLabel}</span>
        {pointer != null && selectedLabel ? (
          <span className="legend-selected">
            {selectedLabel} <b>{scoreFigure(pointer)}</b>
          </span>
        ) : null}
      </div>
      <div className="legend-ramp" aria-hidden="true">
        {CLASSES.map((step, index) => (
          <i
            key={step.from}
            style={{
              backgroundColor: step.color,
              flexGrow: (CLASSES[index + 1]?.from ?? 100) - step.from,
            }}
          />
        ))}
        {pointer != null ? <b className="legend-pointer" style={{ left: `${pointer}%` }} /> : null}
      </div>
      <div className="legend-ticks" aria-hidden="true">
        {TICKS.map((tick) => (
          <span key={tick} style={{ left: `${tick}%` }}>
            {tick}
          </span>
        ))}
      </div>
    </div>
  )
}
