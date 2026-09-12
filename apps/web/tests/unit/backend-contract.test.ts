import { describe, expect, it } from 'vitest'

import { classifyBackendResponse } from '../../server/utils/backend-contract'

describe('classifyBackendResponse', () => {
  it('returns backend data only for successful responses', () => {
    expect(classifyBackendResponse(200, { status: 'ok' })).toEqual({
      state: 'ready',
      data: { status: 'ok' }
    })
  })

  it('marks missing Phase 40 contracts as unavailable without inventing data', () => {
    expect(classifyBackendResponse(404, { detail: 'Not Found' })).toEqual({
      state: 'unavailable',
      message: 'This backend contract is not available yet.'
    })
  })

  it('sanitizes unexpected upstream failures', () => {
    expect(classifyBackendResponse(500, { detail: 'database-password' })).toEqual({
      state: 'error',
      message: 'The backend could not complete this request.'
    })
  })
})
