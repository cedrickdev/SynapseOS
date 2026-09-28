import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ProjectIntakeForm from '../../app/features/projects/ProjectIntakeForm.vue'

describe('ProjectIntakeForm', () => {
  it('emits one canonical intake request from accessible fields', async () => {
    const wrapper = mount(ProjectIntakeForm, {
      props: {
        agents: [{ id: 'agent-id', name: 'Backend Engineer', role: 'Developer' }],
        pending: false,
      },
    })

    await wrapper.get('input[name="name"]').setValue('Control plane')
    await wrapper.get('textarea[name="specification"]').setValue('Build the approved workflow.')
    await wrapper.get('input[name="taskTitle"]').setValue('Implement workflow')
    await wrapper.get('select[name="agentId"]').setValue('agent-id')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([[{
      name: 'Control plane',
      specification: 'Build the approved workflow.',
      taskTitle: 'Implement workflow',
      agentId: 'agent-id',
    }]])
  })

  it('disables duplicate submission while pending', () => {
    const wrapper = mount(ProjectIntakeForm, {
      props: { agents: [], pending: true },
    })

    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
  })
})
