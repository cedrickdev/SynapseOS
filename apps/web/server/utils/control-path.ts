const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const mutationActions = new Set(['approve', 'launch', 'cancel', 'close'])

export function buildControlBackendPath(method: string, segments: readonly string[]): string {
  const normalizedMethod = method.toUpperCase()
  if (normalizedMethod === 'POST' && segments.length === 1 && segments[0] === 'projects') {
    return '/control/projects'
  }
  if (
    segments.length === 3
    && segments[0] === 'projects'
    && typeof segments[1] === 'string'
    && uuidPattern.test(segments[1])
    && typeof segments[2] === 'string'
  ) {
    if (normalizedMethod === 'GET' && segments[2] === 'status') {
      return `/control/projects/${segments[1]}/status`
    }
    if (normalizedMethod === 'POST' && mutationActions.has(segments[2])) {
      return `/control/projects/${segments[1]}/${segments[2]}`
    }
  }
  throw new Error('unsupported control path')
}
