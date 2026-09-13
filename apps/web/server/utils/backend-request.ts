import type { BackendEnvelope } from '../../shared/backend'
import { classifyBackendResponse } from './backend-contract'
import { buildBackendPath } from './backend-path'
import { readBoundedJson } from './backend-response'

interface BackendRequestConfig {
  baseUrl: string
  timeoutMs: number
  maxResponseBytes: number
  serviceToken: string
  query?: Readonly<Record<string, unknown>>
}

type BackendFetcher = (input: string, init: RequestInit) => Promise<Response>

function isValidBound(value: number): boolean {
  return Number.isSafeInteger(value) && value > 0
}

export async function requestBackend(
  resource: string,
  identifier: string | undefined,
  config: BackendRequestConfig,
  fetcher: BackendFetcher = fetch,
): Promise<BackendEnvelope> {
  if (!isValidBound(config.timeoutMs) || !isValidBound(config.maxResponseBytes)) {
    return { state: 'error', message: 'The backend connection is not configured safely.' }
  }
  if (!config.serviceToken) {
    return { state: 'error', message: 'The backend connection is not configured safely.' }
  }

  const path = buildBackendPath(resource, identifier, config.query)
  let target: URL
  try {
    target = new URL(path, config.baseUrl)
  } catch {
    return { state: 'error', message: 'The backend connection is not configured safely.' }
  }

  if (target.protocol !== 'http:' && target.protocol !== 'https:') {
    return { state: 'error', message: 'The backend connection is not configured safely.' }
  }

  try {
    const response = await fetcher(target.toString(), {
      method: 'GET',
      headers: {
        accept: 'application/json',
        'x-synapseos-service-token': config.serviceToken,
      },
      redirect: 'error',
      signal: AbortSignal.timeout(config.timeoutMs),
    })
    const payload = await readBoundedJson(response, config.maxResponseBytes)
    return classifyBackendResponse(response.status, payload)
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw error
    }
    return { state: 'error', message: 'The backend is unreachable or returned an invalid response.' }
  }
}
