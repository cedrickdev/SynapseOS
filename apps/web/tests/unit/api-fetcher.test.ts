import { afterEach, describe, expect, it, vi } from 'vitest'

import { backendFetch } from '../../app/api/backend-fetcher'

describe('backendFetch', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('routes generated API requests through the bounded Nuxt proxy', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      state: 'ready',
      data: { items: [], total: 0, limit: 25, offset: 0 }
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    }))
    vi.stubGlobal('fetch', fetcher)

    await expect(backendFetch('/projects?limit=25&offset=0', {
      method: 'GET'
    })).resolves.toEqual({ items: [], total: 0, limit: 25, offset: 0 })

    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher).toHaveBeenCalledWith(
      '/api/backend/projects?limit=25&offset=0',
      expect.objectContaining({ method: 'GET', redirect: 'error' })
    )
  })

  it('rejects unsupported generated paths before any network request', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)

    await expect(backendFetch('/admin/secrets', { method: 'GET' })).rejects.toThrow(
      'unsupported API path'
    )
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('does not expose upstream error details', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      state: 'error',
      message: 'internal-database-password'
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    }))
    vi.stubGlobal('fetch', fetcher)

    await expect(backendFetch('/projects', { method: 'GET' })).rejects.toThrow(
      'The backend could not complete this request.'
    )
  })
})
