import { describe, expect, it } from 'vitest'

import { summarizeMetrics } from '../../app/features/dashboard/metrics'

describe('summarizeMetrics', () => {
  it('counts bounded aggregate series without treating missing data as zero', () => {
    expect(summarizeMetrics({
      counters: [{ name: 'runtime.completed', labels: [], value: 4 }],
      histograms: [],
      gauges: [{ name: 'runtime.active', labels: [], value: 2 }]
    })).toEqual({ counters: 1, histograms: 0, gauges: 1, totalSeries: 2 })
  })

  it('returns null when the payload is not an aggregate metrics snapshot', () => {
    expect(summarizeMetrics({ error: 'unavailable' })).toBeNull()
  })
})
