<script setup lang="ts">
import {
  useApproveProjectControlProjectsProjectIdApprovePost,
  useCancelWorkflowControlProjectsProjectIdCancelPost,
  useGetProjectProjectsIdentifierGet,
  useLaunchWorkflowControlProjectsProjectIdLaunchPost,
  useWorkflowStatusControlProjectsProjectIdStatusGet,
} from '../../api/generated/dashboard'
import WorkflowControlPanel from '../../features/projects/WorkflowControlPanel.vue'
import WorkflowStatusGrid from '../../features/projects/WorkflowStatusGrid.vue'
import { nextWorkflowPollDelay } from '../../features/projects/workflow-status'

const route = useRoute()
const identifier = computed(() => String(route.params.id))
const project = useGetProjectProjectsIdentifierGet(identifier)
const workflow = useWorkflowStatusControlProjectsProjectIdStatusGet(identifier, {
  query: {
    retry: false,
    refetchInterval: query => nextWorkflowPollDelay(query.state.data),
    refetchIntervalInBackground: false,
  },
})
const approval = useApproveProjectControlProjectsProjectIdApprovePost()
const launch = useLaunchWorkflowControlProjectsProjectIdLaunchPost()
const cancellation = useCancelWorkflowControlProjectsProjectIdCancelPost()
const actionError = ref<string>()

const actionPending = computed(() => (
  approval.isPending.value || launch.isPending.value || cancellation.isPending.value
))

async function refreshAuthoritativeState(): Promise<void> {
  await Promise.all([project.refetch(), workflow.refetch()])
}

function commandBase(prefix: string): {
  command_id: string
  correlation_id: string
  idempotency_key: string
} {
  const commandId = crypto.randomUUID()
  return {
    command_id: commandId,
    correlation_id: crypto.randomUUID(),
    idempotency_key: `${prefix}-${commandId}`,
  }
}

async function runAction(action: () => Promise<unknown>): Promise<void> {
  actionError.value = undefined
  try {
    await action()
    await refreshAuthoritativeState()
  } catch (error) {
    actionError.value = error instanceof Error
      ? error.message
      : 'The backend could not complete this request.'
  }
}

async function approve(evidenceId: string): Promise<void> {
  const status = workflow.data.value
  const taskId = status?.task_id
  if (!taskId) return
  await runAction(() => approval.mutateAsync({
    projectId: identifier.value,
    data: {
      ...commandBase('approval'),
      project_id: identifier.value,
      task_id: taskId,
      evidence_id: evidenceId,
    },
  }))
}

async function launchWorkflow(): Promise<void> {
  const status = workflow.data.value
  const taskId = status?.task_id
  if (!taskId) return
  await runAction(() => launch.mutateAsync({
    projectId: identifier.value,
    data: {
      ...commandBase('launch'),
      project_id: identifier.value,
      task_id: taskId,
      timeout_seconds: 900,
    },
  }))
}

async function cancelWorkflow(): Promise<void> {
  const status = workflow.data.value
  const runId = status?.run_id
  if (!runId) return
  await runAction(() => cancellation.mutateAsync({
    projectId: identifier.value,
    data: {
      ...commandBase('cancel'),
      project_id: identifier.value,
      run_id: runId,
    },
  }))
}
</script>

<template>
  <div class="page-stack">
    <PageHeading
      :title="project.data.value?.name ?? 'Project detail'"
      description="Authoritative workflow state, independent gates and human controls."
      icon="i-lucide-panel-top"
    >
      <button class="secondary-button" type="button" :disabled="workflow.isFetching.value" @click="refreshAuthoritativeState">
        <UIcon name="i-lucide-refresh-cw" aria-hidden="true" /> Refresh
      </button>
    </PageHeading>

    <ContractState v-if="project.isPending.value || workflow.isPending.value" state="loading" />
    <ContractState
      v-else-if="project.isError.value || workflow.isError.value || !workflow.data.value"
      state="error"
      message="The authoritative project state is unavailable."
      @retry="refreshAuthoritativeState"
    />
    <template v-else>
      <WorkflowStatusGrid :status="workflow.data.value" />
      <WorkflowControlPanel
        :status="workflow.data.value"
        :pending="actionPending"
        :error="actionError"
        @approve="approve"
        @launch="launchWorkflow"
        @cancel="cancelWorkflow"
      />
    </template>
  </div>
</template>
