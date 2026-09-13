import type { BackendEnvelope, BackendResource } from '../../shared/backend'

const API_TIMEOUT_MS = 10_000
const identifierPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const pathResources = new Map<string, BackendResource>([
  ['/health', 'health'],
  ['/internal/metrics', 'metrics'],
  ['/projects', 'projects'],
  ['/tasks', 'tasks'],
  ['/agents', 'agents'],
  ['/runs', 'runs'],
  ['/audit', 'audit'],
  ['/feedback', 'feedback'],
  ['/security-findings', 'security'],
  ['/costs', 'costs'],
])

function buildProxyPath(url: string): string {
  const target = new URL(url, 'http://synapseos.invalid')
  const segments = target.pathname.split('/').filter(Boolean)
  const basePath = segments.length > 1 ? `/${segments.slice(0, -1).join('/')}` : target.pathname
  const resource = pathResources.get(basePath) ?? pathResources.get(target.pathname)
  if (!resource) {
    throw new Error('unsupported API path')
  }

  const matchedBase = pathResources.has(target.pathname) ? target.pathname : basePath
  const identifier = target.pathname === matchedBase ? undefined : segments.at(-1)
  if (identifier !== undefined && !identifierPattern.test(identifier)) {
    throw new Error('unsupported API path')
  }

  for (const key of target.searchParams.keys()) {
    if (key !== 'limit' && key !== 'offset') {
      throw new Error('unsupported API query')
    }
  }

  const suffix = identifier === undefined ? '' : `/${encodeURIComponent(identifier)}`
  return `/api/backend/${resource}${suffix}${target.search}`
}

function unwrapEnvelope<T>(payload: BackendEnvelope): T {
  if (payload.state === 'ready') {
    return payload.data as T
  }
  if (payload.state === 'unavailable') {
    throw new Error('This backend contract is not available yet.')
  }
  throw new Error('The backend could not complete this request.')
}

export async function backendFetch<T>(url: string, options: RequestInit): Promise<T> {
  const proxyPath = buildProxyPath(url)
  const timeoutSignal = AbortSignal.timeout(API_TIMEOUT_MS)
  const signal = options.signal
    ? AbortSignal.any([options.signal, timeoutSignal])
    : timeoutSignal
  const response = await fetch(proxyPath, {
    ...options,
    headers: { accept: 'application/json' },
    redirect: 'error',
    signal,
  })
  if (!response.ok) {
    throw new Error('The backend could not complete this request.')
  }
  return unwrapEnvelope<T>(await response.json() as BackendEnvelope)
}
