import { useState } from 'react'
import type { LatLng } from 'leaflet'
import { useMap, useMapEvents } from 'react-leaflet'
import { formatCoordinates } from '../lib/format'

/**
 * Coordinate readout in the map margin: the position under the pointer, or the
 * centre of the view when there is no pointer (touch, keyboard), plus the zoom.
 * Rendered as a child of the MapContainer, so it lives inside the map element.
 */
export function MapReadout() {
  const map = useMap()
  const [pointer, setPointer] = useState<LatLng | null>(null)
  const [view, setView] = useState(() => ({ center: map.getCenter(), zoom: map.getZoom() }))

  useMapEvents({
    mousemove: (event) => setPointer(event.latlng),
    mouseout: () => setPointer(null),
    moveend: () => setView({ center: map.getCenter(), zoom: map.getZoom() }),
  })

  const position = pointer ?? view.center

  return (
    <div className="map-readout" aria-hidden="true">
      <span>{pointer ? 'Pointer' : 'Centre'}</span>
      {formatCoordinates(position.lat, position.lng)}
      <span>Zoom</span>
      {view.zoom}
    </div>
  )
}
