// Writes the server's country list from the same Natural Earth data the map draws,
// so both applications agree on country codes.
import { readFileSync, writeFileSync } from 'node:fs'

const atlas = JSON.parse(readFileSync(new URL('../node_modules/world-atlas/countries-110m.json', import.meta.url)))
const countries = {}
for (const g of atlas.objects.countries.geometries) {
  // A few disputed areas have no ISO code, and Antarctica is not a nation
  if (g.id && g.properties.name !== 'Antarctica') countries[g.id] = g.properties.name
}
const out = new URL('../../server/app/data/countries.json', import.meta.url)
writeFileSync(out, JSON.stringify(countries, null, 1) + '\n')
console.log(`Wrote ${Object.keys(countries).length} countries`)
