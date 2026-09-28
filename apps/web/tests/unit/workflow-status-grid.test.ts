import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WorkflowStatusGrid from '../../app/features/projects/WorkflowStatusGrid.vue'

const status = {
  project_id: 'project-id',
  project_status: 'IN_PROGRESS',
  task_id: 'task-id',
  task_status: 'BLOCKED',
  run_id: 'run-id',
  queue_status: 'RUNNING',
  assigned_agent_id: 'agent-id',
  current_stage: 'BLOCKED',
  blockers: ['TASK_BLOCKED', 'SECURITY_BLOCKED'],
  provider_cost_total: '0.12500000',
  qa_status: 'PASSED',
  security_status: 'BLOCKED',
  human_approval: true,
  merge_gate_status: 'BLOCKED',
  terminal: false,
}

describe('WorkflowStatusGrid', () => {
  it('renders authoritative stage, assignment, cost, blockers, and independent gates', () => {
    const wrapper = mount(WorkflowStatusGrid, { props: { status } })

    expect(wrapper.get('[data-status="stage"]').text()).toContain('BLOCKED')
    expect(wrapper.get('[data-status="agent"]').text()).toContain('agent-id')
    expect(wrapper.get('[data-status="cost"]').text()).toContain('0.12500000')
    expect(wrapper.get('[data-status="blockers"]').text()).toContain('TASK_BLOCKED, SECURITY_BLOCKED')
    expect(wrapper.get('[data-status="security"]').text()).toContain('BLOCKED')
  })
})
