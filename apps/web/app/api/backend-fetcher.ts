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

const uuidPattern = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}'
const controlActionPattern = new RegExp(`^/control/projects/${uuidPattern}/(approve|launch|cancel|close)$`)
const controlStatusPattern = new RegExp(`^/control/projects/${uuidPattern}/status$`)

function buildProxyPath(url: string, method: string): string {
  const target = new URL(url, 'http://synapseos.invalid')
  if (target.search || target.hash) {
    if (target.pathname.startsWith('/control/')) {
      throw new Error('unsupported API path')
    }
  }
  if (
    (method === 'POST' && (target.pathname === '/control/projects' || controlActionPattern.test(target.pathname)))
    || (method === 'GET' && controlStatusPattern.test(target.pathname))
  ) {
    return `/api${target.pathname}`
  }
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
  const safeMessages = new Set([
    'Your session expired. Sign in again.',
    'You do not have permission to perform this action.',
    'The project changed. Refresh its status before trying again.',
    'The workflow service is temporarily unavailable.',
    'The backend is unreachable or returned an invalid response.',
    'The backend could not complete this request.',
  ])
  throw new Error(safeMessages.has(payload.message)
    ? payload.message
    : 'The backend could not complete this request.')
}

export async function backendFetch<T>(url: string, options: RequestInit): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const proxyPath = buildProxyPath(url, method)
  const timeoutSignal = AbortSignal.timeout(API_TIMEOUT_MS)
  const signal = options.signal
    ? AbortSignal.any([options.signal, timeoutSignal])
    : timeoutSignal
  const response = await fetch(proxyPath, {
    ...options,
    method,
    headers: method === 'POST'
      ? { accept: 'application/json', 'content-type': 'application/json' }
      : { accept: 'application/json' },
    redirect: 'error',
    signal,
  })
  if (!response.ok) {
    throw new Error('The backend could not complete this request.')
  }
  return unwrapEnvelope<T>(await response.json() as BackendEnvelope)
}
