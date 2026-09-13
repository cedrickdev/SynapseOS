import { backendResources, type BackendResource } from '../../shared/backend'

const backendPaths: Record<BackendResource, string> = {
  health: '/health',
  metrics: '/internal/metrics',
  projects: '/projects',
  tasks: '/tasks',
  agents: '/agents',
  runs: '/runs',
  audit: '/audit',
  feedback: '/feedback',
  security: '/security-findings',
  costs: '/costs',
}

const resourceIdentifiers = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const paginationBounds = {
  limit: { minimum: 1, maximum: 100 },
  offset: { minimum: 0, maximum: 10_000 },
} as const

function buildPaginationQuery(query: Readonly<Record<string, unknown>>): string {
  const search = new URLSearchParams()
  for (const key of ['limit', 'offset'] as const) {
    const value = query[key]
    if (value === undefined) {
      continue
    }
    if (typeof value !== 'string' || !/^\d+$/.test(value)) {
      throw new Error('invalid backend query')
    }
    const parsed = Number(value)
    const bounds = paginationBounds[key]
    if (!Number.isSafeInteger(parsed) || parsed < bounds.minimum || parsed > bounds.maximum) {
      throw new Error('invalid backend query')
    }
    search.set(key, String(parsed))
  }
  if (Object.keys(query).some(key => !(key in paginationBounds))) {
    throw new Error('invalid backend query')
  }
  const serialized = search.toString()
  return serialized ? `?${serialized}` : ''
}

export function buildBackendPath(
  resource: string,
  identifier?: string,
  query: Readonly<Record<string, unknown>> = {},
): string {
  if (!backendResources.includes(resource as BackendResource)) {
    throw new Error('unsupported backend resource')
  }

  const basePath = backendPaths[resource as BackendResource]
  if (identifier === undefined) {
    return `${basePath}${buildPaginationQuery(query)}`
  }

  if (!resourceIdentifiers.test(identifier) || Object.keys(query).length > 0) {
    throw new Error('invalid resource identifier')
  }

  return `${basePath}/${encodeURIComponent(identifier)}`
}
