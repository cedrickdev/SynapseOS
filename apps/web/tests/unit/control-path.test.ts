import { describe, expect, it } from 'vitest'

import { buildControlBackendPath } from '../../server/utils/control-path'

const projectId = '123e4567-e89b-12d3-a456-426614174000'

describe('buildControlBackendPath', () => {
  it('allows only the bounded control routes and methods', () => {
    expect(buildControlBackendPath('POST', ['projects'])).toBe('/control/projects')
    expect(buildControlBackendPath('GET', ['projects', projectId, 'status'])).toBe(
      `/control/projects/${projectId}/status`
    )
    expect(buildControlBackendPath('POST', ['projects', projectId, 'approve'])).toBe(
      `/control/projects/${projectId}/approve`
    )
  })

  it('rejects traversal, unknown actions, and method confusion', () => {
    expect(() => buildControlBackendPath('POST', ['projects', '../secrets', 'launch'])).toThrow(
      'unsupported control path'
    )
    expect(() => buildControlBackendPath('POST', ['projects', projectId, 'retry'])).toThrow(
      'unsupported control path'
    )
    expect(() => buildControlBackendPath('GET', ['projects', projectId, 'cancel'])).toThrow(
      'unsupported control path'
    )
  })
})
