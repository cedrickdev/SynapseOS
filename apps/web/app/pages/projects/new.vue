<script setup lang="ts">
import {
  useIntakeProjectControlProjectsPost,
  useListAgentsAgentsGet,
} from '../../api/generated/dashboard'
import ProjectIntakeForm from '../../features/projects/ProjectIntakeForm.vue'

const agents = useListAgentsAgentsGet({ limit: 100, offset: 0 })
const intake = useIntakeProjectControlProjectsPost()
const errorMessage = ref<string>()

async function submit(draft: {
  name: string
  specification: string
  taskTitle: string
  agentId: string
}): Promise<void> {
  errorMessage.value = undefined
  const commandId = crypto.randomUUID()
  try {
    const result = await intake.mutateAsync({
      data: {
        command_id: commandId,
        correlation_id: crypto.randomUUID(),
        idempotency_key: `intake-${commandId}`,
        name: draft.name,
        specification: draft.specification,
        task_title: draft.taskTitle,
        assigned_agent_id: draft.agentId,
      },
    })
    await navigateTo(`/projects/${result.project_id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error
      ? error.message
      : 'The backend could not complete this request.'
  }
}
</script>

<template>
  <div class="page-stack">
    <PageHeading
      title="Create project"
      description="Create the project and its first authoritative task. The backend validates scope, assignment and permissions."
      icon="i-lucide-folder-plus"
    />
    <ContractState v-if="agents.isPending.value" state="loading" />
    <ProjectIntakeForm
      v-else
      :agents="agents.data.value?.items ?? []"
      :pending="intake.isPending.value"
      :error="errorMessage"
      @submit="submit"
    />
  </div>
</template>
