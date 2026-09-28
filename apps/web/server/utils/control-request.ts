import type { BackendEnvelope } from '../../shared/backend'
import { readBoundedJson } from './backend-response'
import { isAbortError } from './oidc-client'

interface ControlRequestConfig {
  readonly baseUrl: string
  readonly timeoutMs: number
  readonly maxResponseBytes: number
  readonly serviceToken: string
  readonly accessToken: string
  readonly companyId: string
}

type BackendFetcher = (input: string, init: RequestInit) => Promise<Response>

function safeControlError(status: number): BackendEnvelope {
  if (status === 401) {
    return { state: 'error', message: 'Your session expired. Sign in again.' }
  }
  if (status === 403) {
    return { state: 'error', message: 'You do not have permission to perform this action.' }
  }
  if (status === 409) {
    return { state: 'error', message: 'The project changed. Refresh its status before trying again.' }
  }
  if (status === 503) {
    return { state: 'error', message: 'The workflow service is temporarily unavailable.' }
  }
  return { state: 'error', message: 'The backend could not complete this request.' }
}

export async function requestControlBackend(
  path: string,
  method: 'GET' | 'POST',
  body: Readonly<Record<string, unknown>> | undefined,
  config: ControlRequestConfig,
  fetcher: BackendFetcher = fetch,
  cancellationSignal?: AbortSignal,
): Promise<BackendEnvelope> {
  if (
    !path.startsWith('/control/')
    || !Number.isSafeInteger(config.timeoutMs)
    || config.timeoutMs <= 0
    || !Number.isSafeInteger(config.maxResponseBytes)
    || config.maxResponseBytes <= 0
    || !config.serviceToken
    || !config.accessToken
    || !config.companyId
  ) {
    return { state: 'error', message: 'The backend connection is not configured safely.' }
  }
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
    const timeoutSignal = AbortSignal.timeout(config.timeoutMs)
    const signal = cancellationSignal
      ? AbortSignal.any([cancellationSignal, timeoutSignal])
      : timeoutSignal
    const response = await fetcher(target.toString(), {
      method,
      headers: {
        accept: 'application/json',
        authorization: `Bearer ${config.accessToken}`,
        ...(method === 'POST' ? { 'content-type': 'application/json' } : {}),
        'x-synapseos-company-id': config.companyId,
        'x-synapseos-service-token': config.serviceToken,
      },
      ...(method === 'POST' ? { body: JSON.stringify(body ?? {}) } : {}),
      redirect: 'error',
      signal,
    })
    const payload = await readBoundedJson(response, config.maxResponseBytes)
    return response.ok ? { state: 'ready', data: payload } : safeControlError(response.status)
  } catch (error) {
    if (isAbortError(error) || cancellationSignal?.aborted) {
      throw error
    }
    return { state: 'error', message: 'The backend is unreachable or returned an invalid response.' }
  }
}
