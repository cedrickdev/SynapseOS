export type StatusTone = 'positive' | 'warning' | 'danger' | 'info' | 'neutral'

export interface StatusDescription {
  tone: StatusTone
  icon: string
  label: string
}

const statusDescriptions: Readonly<Record<string, StatusDescription>> = {
  AVAILABLE: { tone: 'positive', icon: 'circle-check', label: 'Available' },
  WORKING: { tone: 'info', icon: 'loader-circle', label: 'Working' },
  IN_PROGRESS: { tone: 'info', icon: 'loader-circle', label: 'In progress' },
  BLOCKED: { tone: 'danger', icon: 'octagon-alert', label: 'Blocked' },
  FAILED: { tone: 'danger', icon: 'circle-x', label: 'Failed' },
  COMPLETED: { tone: 'positive', icon: 'circle-check', label: 'Completed' },
  SUCCEEDED: { tone: 'positive', icon: 'circle-check', label: 'Succeeded' },
  WAITING_REVIEW: { tone: 'warning', icon: 'scan-search', label: 'Waiting for review' },
  WAITING_QA: { tone: 'warning', icon: 'flask-conical', label: 'Waiting for QA' },
  WAITING_SECURITY: { tone: 'warning', icon: 'shield-alert', label: 'Waiting for security' },
  CANCELLED: { tone: 'neutral', icon: 'circle-slash-2', label: 'Cancelled' }
}

function humanizeCanonicalValue(value: string): string {
  const lower = value.trim().replaceAll('_', ' ').toLocaleLowerCase('en-US')
  return lower ? `${lower[0]?.toLocaleUpperCase('en-US') ?? ''}${lower.slice(1)}` : 'Unknown'
}

export function describeStatus(status: string): StatusDescription {
  return statusDescriptions[status] ?? {
    tone: 'neutral',
    icon: 'circle-dashed',
    label: humanizeCanonicalValue(status)
  }
}
