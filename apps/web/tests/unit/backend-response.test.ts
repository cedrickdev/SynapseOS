import { describe, expect, it } from 'vitest'

import { readBoundedJson } from '../../server/utils/backend-response'

describe('readBoundedJson', () => {
  it('parses a JSON response within the byte budget', async () => {
    const response = new Response('{"status":"ok"}', {
      headers: { 'content-type': 'application/json' }
    })

    await expect(readBoundedJson(response, 64)).resolves.toEqual({ status: 'ok' })
  })

  it('rejects an upstream response larger than the byte budget', async () => {
    const response = new Response('{"value":"too large"}', {
      headers: { 'content-type': 'application/json' }
    })

    await expect(readBoundedJson(response, 8)).rejects.toThrow('response exceeded the configured limit')
  })

  it('rejects non-JSON upstream content without echoing the body', async () => {
    const secret = 'provider-secret-value'
    const response = new Response(secret, {
      headers: { 'content-type': 'text/plain' }
    })

    await expect(readBoundedJson(response, 64)).rejects.not.toThrow(secret)
  })
})
