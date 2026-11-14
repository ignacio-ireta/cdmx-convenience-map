import type { Locator } from '../lib/locator'
import type { AreaFeature } from '../types'

/**
 * Locator inset for the sheet's title block: every scored area as a hairline
 * mesh in the city's ink, with the selected area marked in the counter ink.
 */
export function LocatorInset({
  caption,
  locator,
  selected,
}: {
  caption: string
  locator: Locator
  selected: AreaFeature | null
}) {
  const lat = selected?.properties.centroid_lat
  const lon = selected?.properties.centroid_lon
  const mark =
    typeof lat === 'number' && typeof lon === 'number' && Number.isFinite(lat + lon)
      ? locator.project(lon, lat)
      : null

  return (
    <figure className="locator">
      <svg
        viewBox={`0 0 ${locator.width} ${locator.height}`}
        width={locator.width}
        height={locator.height}
        role="img"
        aria-label={caption}
      >
        <path className="locator-mesh" d={locator.mesh} />
        {selected?.geometry ? (
          <path className="locator-selected" d={locator.outline(selected.geometry)} />
        ) : null}
        {mark ? (
          <g
            className="locator-mark"
            style={{ transform: `translate(${mark[0]}px, ${mark[1]}px)` }}
          >
            <circle r="6" />
            <path d="M-10 0H-6M6 0H10M0 -10V-6M0 6V10" />
          </g>
        ) : null}
      </svg>
      <figcaption>{caption}</figcaption>
    </figure>
  )
}
