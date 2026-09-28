import { describe, expect, it } from 'vitest'

import { nextWorkflowPollDelay } from '../../app/features/projects/workflow-status'

describe('nextWorkflowPollDelay', () => {
  it('polls active workflows at one bounded interval and stops at terminal state', () => {
    expect(nextWorkflowPollDelay({ terminal: false })).toBe(3_000)
    expect(nextWorkflowPollDelay({ terminal: true })).toBe(false)
    expect(nextWorkflowPollDelay(undefined)).toBe(false)
  })
})
