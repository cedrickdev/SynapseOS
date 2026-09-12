import type { BackendEnvelope, BackendResource } from '../../shared/backend'

export function useBackendResource(resource: BackendResource, identifier?: string) {
  const path = identifier
    ? `/api/backend/${resource}/${encodeURIComponent(identifier)}`
    : `/api/backend/${resource}`

  return useFetch<BackendEnvelope>(path, {
    key: `backend:${resource}:${identifier ?? 'collection'}`,
    retry: 0,
    timeout: 10_000,
  })
}
