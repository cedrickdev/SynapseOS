export const backendResources = [
  'health',
  'metrics',
  'projects',
  'tasks',
  'agents',
  'runs',
  'audit',
  'feedback',
  'security',
  'costs',
] as const

export type BackendResource = (typeof backendResources)[number]

export type BackendEnvelope =
  | { state: 'ready', data: unknown }
  | { state: 'unavailable', message: string }
  | { state: 'error', message: string }
