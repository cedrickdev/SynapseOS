import { describe, expect, it } from 'vitest'

import { buildBackendPath } from '../../server/utils/backend-path'

describe('buildBackendPath', () => {
  it('maps an allowlisted collection to its backend path', () => {
    expect(buildBackendPath('projects')).toBe('/projects')
  })

  it('encodes a bounded identifier without allowing path traversal', () => {
    expect(buildBackendPath('agents', 'backend-agent-03')).toBe('/agents/backend-agent-03')
    expect(() => buildBackendPath('agents', '../secrets')).toThrow('invalid resource identifier')
  })

  it('rejects resources that are not explicitly allowlisted', () => {
    expect(() => buildBackendPath('shell')).toThrow('unsupported backend resource')
  })
})
