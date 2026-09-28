import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import WorkflowControlPanel from '../../app/features/projects/WorkflowControlPanel.vue'

const status = {
  project_id: 'project-id',
  project_status: 'IN_PROGRESS',
  task_id: 'task-id',
  task_status: 'READY',
  run_id: 'run-id',
  queue_status: 'RUNNING',
  assigned_agent_id: 'agent-id',
  current_stage: 'EXECUTION',
  blockers: [],
  provider_cost_total: '0',
  qa_status: 'PENDING',
  security_status: 'PENDING',
  human_approval: false,
  merge_gate_status: 'BLOCKED',
  terminal: false,
}

describe('WorkflowControlPanel', () => {
  it('requires explicit confirmation before emitting cancellation', async () => {
    const wrapper = mount(WorkflowControlPanel, { props: { status, pending: false } })

    await wrapper.get('[data-action="cancel"]').trigger('click')
    expect(wrapper.emitted('cancel')).toBeUndefined()
    await wrapper.get('[data-action="confirm-cancel"]').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('exposes approval and launch actions only with an authoritative task', async () => {
    const wrapper = mount(WorkflowControlPanel, { props: { status, pending: false } })

    await wrapper.get('input[name="evidenceId"]').setValue('human-approval-1')
    await wrapper.get('[data-action="approve"]').trigger('click')
    await wrapper.get('[data-action="launch"]').trigger('click')

    expect(wrapper.emitted('approve')).toEqual([['human-approval-1']])
    expect(wrapper.emitted('launch')).toHaveLength(1)
  })
})
