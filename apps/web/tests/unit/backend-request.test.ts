import { describe, expect, it, vi } from 'vitest'

import { requestBackend } from '../../server/utils/backend-request'

describe('requestBackend', () => {
  it('performs exactly one bounded request and returns classified data', async () => {
    const fetcher = vi.fn(async () => new Response('{"status":"ok"}', {
      status: 200,
      headers: { 'content-type': 'application/json' }
    }))

    await expect(requestBackend('health', undefined, {
      baseUrl: 'http://backend:8000',
      timeoutMs: 500,
      maxResponseBytes: 128,
      serviceToken: 'private-dashboard-token'
    }, fetcher)).resolves.toEqual({ state: 'ready', data: { status: 'ok' } })

    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith('http://backend:8000/health', expect.objectContaining({
      method: 'GET',
      redirect: 'error',
      headers: {
        accept: 'application/json',
        'x-synapseos-service-token': 'private-dashboard-token'
      }
    }))
  })

  it('does not expose an upstream body when the request fails', async () => {
    const secret = 'internal-database-password'
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ detail: secret }), {
      status: 500,
      headers: { 'content-type': 'application/json' }
    }))

    const result = await requestBackend('projects', undefined, {
      baseUrl: 'http://backend:8000',
      timeoutMs: 500,
      maxResponseBytes: 128,
      serviceToken: 'private-dashboard-token'
    }, fetcher)

    expect(JSON.stringify(result)).not.toContain(secret)
  })

  it('rejects an empty service token without contacting the backend', async () => {
    const fetcher = vi.fn()

    await expect(requestBackend('projects', undefined, {
      baseUrl: 'http://backend:8000',
      timeoutMs: 500,
      maxResponseBytes: 128,
      serviceToken: ''
    }, fetcher)).resolves.toEqual({
      state: 'error',
      message: 'The backend connection is not configured safely.'
    })

    expect(fetcher).not.toHaveBeenCalled()
  })

  it('propagates cancellation instead of converting it into an application error', async () => {
    const cancellation = new DOMException('request cancelled', 'AbortError')
    const fetcher = vi.fn(async () => Promise.reject(cancellation))

    await expect(requestBackend('projects', undefined, {
      baseUrl: 'http://backend:8000',
      timeoutMs: 500,
      maxResponseBytes: 128,
      serviceToken: 'private-dashboard-token'
    }, fetcher)).rejects.toBe(cancellation)

    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
