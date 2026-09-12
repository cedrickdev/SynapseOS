export interface NavigationItem {
  label: string
  description: string
  icon: string
  to: string
}

export interface NavigationSection {
  label: string
  items: readonly NavigationItem[]
}

export const navigationSections: readonly NavigationSection[] = [
  {
    label: 'Company',
    items: [
      { label: 'Dashboard', description: 'Company pulse', icon: 'i-lucide-layout-dashboard', to: '/' }
    ]
  },
  {
    label: 'Delivery',
    items: [
      { label: 'Projects', description: 'Portfolio and milestones', icon: 'i-lucide-panels-top-left', to: '/projects' },
      { label: 'Tasks', description: 'Work and gates', icon: 'i-lucide-list-checks', to: '/tasks' },
      { label: 'Agents', description: 'Company directory', icon: 'i-lucide-bot', to: '/agents' },
      { label: 'Runs', description: 'Runtime evidence', icon: 'i-lucide-activity', to: '/runs' }
    ]
  },
  {
    label: 'Governance',
    items: [
      { label: 'Audit', description: 'Immutable evidence', icon: 'i-lucide-scroll-text', to: '/audit' },
      { label: 'Feedback', description: 'Client signals', icon: 'i-lucide-message-square-text', to: '/feedback' },
      { label: 'Security', description: 'Findings and vetoes', icon: 'i-lucide-shield-check', to: '/security' },
      { label: 'Costs', description: 'Usage and budgets', icon: 'i-lucide-chart-no-axes-combined', to: '/costs' }
    ]
  },
  {
    label: 'System',
    items: [
      { label: 'Settings', description: 'Safe preferences', icon: 'i-lucide-settings-2', to: '/settings' }
    ]
  }
] as const

export const commandNavigationItems = navigationSections.flatMap(section => section.items)
