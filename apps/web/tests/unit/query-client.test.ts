import { describe, expect, it } from 'vitest'

import { createDashboardQueryClient } from '../../app/api/query-client'

describe('createDashboardQueryClient', () => {
  it('disables implicit retries and bounds cached dashboard history', () => {
    const options = createDashboardQueryClient().getDefaultOptions().queries

    expect(options?.retry).toBe(false)
    expect(options?.staleTime).toBe(15_000)
    expect(options?.gcTime).toBe(300_000)
  })
})
