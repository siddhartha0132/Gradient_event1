/** Country shapes from Natural Earth (bundled), projected once with D3. */
import { geoCentroid, geoNaturalEarth1, geoPath } from 'd3-geo'
import type { Feature, Geometry } from 'geojson'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import atlas from 'world-atlas/countries-110m.json'

export const MAP_WIDTH = 960
export const MAP_HEIGHT = 500

export type Country = { code: string; name: string; d: string; center: [number, number] }

let cache: Country[] | null = null

export function countries(): Country[] {
  if (cache) return cache
  const topology = atlas as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>
  const collection = feature(topology, topology.objects.countries)
  const projection = geoNaturalEarth1().fitExtent(
    [
      [4, 4],
      [MAP_WIDTH - 4, MAP_HEIGHT - 4],
    ],
    collection,
  )
  const path = geoPath(projection)
  cache = collection.features
    .filter((f) => f.id !== undefined && f.properties.name !== 'Antarctica')
    .map((f: Feature<Geometry, { name: string }>) => {
      const centroid = projection(geoCentroid(f)) ?? [0, 0]
      return { code: String(f.id), name: f.properties.name, d: path(f) ?? '', center: centroid as [number, number] }
    })
  return cache
}

export function countryByCode(): Map<string, Country> {
  return new Map(countries().map((c) => [c.code, c]))
}

/** A curved arc between two points, bowing upwards like a flight path. */
export function arcPath(a: [number, number], b: [number, number]) {
  const [x1, y1] = a
  const [x2, y2] = b
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2 - Math.hypot(x2 - x1, y2 - y1) * 0.3
  return { d: `M${x1},${y1} Q${mx},${my} ${x2},${y2}`, length: Math.hypot(x2 - x1, y2 - y1) * 1.25 }
}

const PALETTE = ['#4b7bec', '#f5a524', '#22c55e', '#e056fd', '#2bcbba', '#fd9644', '#a5b1c2', '#45aaf2', '#fed330', '#26de81']

/** A stable colour per team. */
export function teamColor(teamId: string) {
  let h = 0
  for (const c of teamId) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}
