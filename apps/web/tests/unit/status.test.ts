import { describe, expect, it } from 'vitest'

import { describeStatus } from '../../app/utils/status'

describe('describeStatus', () => {
  it('returns a semantic label and icon for known backend states', () => {
    expect(describeStatus('BLOCKED')).toEqual({ tone: 'danger', icon: 'octagon-alert', label: 'Blocked' })
  })

  it('preserves an unknown canonical state as readable text', () => {
    expect(describeStatus('WAITING_CUSTOM_GATE')).toEqual({
      tone: 'neutral',
      icon: 'circle-dashed',
      label: 'Waiting custom gate'
    })
  })
})
