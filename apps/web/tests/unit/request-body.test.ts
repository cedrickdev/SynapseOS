import { describe, expect, it } from 'vitest'

import { readBoundedRequestJson } from '../../server/utils/request-body'

async function* chunks(...values: string[]): AsyncGenerator<Uint8Array> {
  for (const value of values) {
    yield new TextEncoder().encode(value)
  }
}

describe('readBoundedRequestJson', () => {
  it('parses one bounded JSON object', async () => {
    await expect(readBoundedRequestJson(chunks('{"name":', '"project"}'), 32))
      .resolves.toEqual({ name: 'project' })
  })

  it('rejects oversized, malformed, or non-object bodies', async () => {
    await expect(readBoundedRequestJson(chunks('{"value":"too large"}'), 8))
      .rejects.toThrow('invalid control request')
    await expect(readBoundedRequestJson(chunks('[]'), 8))
      .rejects.toThrow('invalid control request')
    await expect(readBoundedRequestJson(chunks('{broken'), 32))
      .rejects.toThrow('invalid control request')
  })
})
