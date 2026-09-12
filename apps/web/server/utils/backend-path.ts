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

export function buildBackendPath(resource: string, identifier?: string): string {
  if (!backendResources.includes(resource as BackendResource)) {
    throw new Error('unsupported backend resource')
  }

  const basePath = backendPaths[resource as BackendResource]
  if (identifier === undefined) {
    return basePath
  }

  if (!resourceIdentifiers.test(identifier)) {
    throw new Error('invalid resource identifier')
  }

  return `${basePath}/${encodeURIComponent(identifier)}`
}
