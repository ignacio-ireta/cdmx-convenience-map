import type { AreaProperties, AreaUnit } from '../types'

export function areaUnitLabel(unit: AreaUnit) {
  return unit === 'postal_code' ? 'Postal code' : 'Colonia'
}

export function areaShortLabel(properties: AreaProperties) {
  return properties.area_unit === 'postal_code'
    ? `CP ${properties.postal_code ?? properties.area_id}`
    : properties.display_name
}

export function areaFullLabel(properties: AreaProperties) {
  const base = areaShortLabel(properties)
  return properties.alcaldia ? `${base}, ${properties.alcaldia}` : base
}

export function areaResultLabel(properties: AreaProperties) {
  const primary =
    properties.area_unit === 'postal_code'
      ? `CP ${properties.postal_code ?? properties.area_id}`
      : properties.colonia_name || properties.area_name || properties.display_name
  return properties.alcaldia ? `${primary} — ${properties.alcaldia}` : primary
}

export function normalizeSearchText(value: string) {
  return value
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
}

export function areaSearchFields(properties: AreaProperties) {
  return [
    properties.area_id,
    properties.area_name,
    properties.display_name,
    properties.postal_code,
    properties.d_cp,
    properties.postal_label,
    properties.colonia_name,
    properties.alcaldia,
  ].filter((value): value is string => Boolean(value))
}

export function areaSearchText(properties: AreaProperties) {
  return areaSearchFields(properties).map(normalizeSearchText).join(' ')
}

export function getAreaSearchRank(
  properties: AreaProperties,
  normalizedQuery: string,
  postalQuery: string,
) {
  const fields = areaSearchFields(properties).map(normalizeSearchText)
  const haystack = areaSearchText(properties)

  if (
    postalQuery &&
    properties.area_unit === 'postal_code' &&
    properties.postal_code === postalQuery
  ) {
    return 0
  }

  if (!normalizedQuery) return null
  if (fields.some((field) => field === normalizedQuery)) return 1
  if (fields.some((field) => field.startsWith(normalizedQuery))) return 2
  if (fields.some((field) => field.split(' ').some((token) => token.startsWith(normalizedQuery)))) {
    return 3
  }
  if (haystack.includes(normalizedQuery)) return 4
  return null
}

export function toggleRequiredSelection<Key extends string>(current: Key[], key: Key): Key[] {
  if (current.includes(key)) {
    return current.length === 1 ? current : current.filter((item) => item !== key)
  }
  return [...current, key]
}
