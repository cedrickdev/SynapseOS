<script setup lang="ts">
import { ref } from 'vue'

import type { WorkflowStatus } from '../../api/generated/models'

const props = defineProps<{
  status: WorkflowStatus
  pending: boolean
  error?: string | undefined
}>()
const emit = defineEmits<{
  approve: [evidenceId: string]
  launch: []
  cancel: []
}>()

const evidenceId = ref('')
const confirmingCancel = ref(false)

function approve(): void {
  const evidence = evidenceId.value.trim()
  if (evidence && props.status.task_id && !props.pending) {
    emit('approve', evidence)
  }
}
</script>

<template>
  <section class="operational-panel workflow-controls" aria-labelledby="workflow-controls-title">
    <header>
      <div>
        <h2 id="workflow-controls-title">Workflow controls</h2>
        <p>Commands are validated and authorized by the backend.</p>
      </div>
    </header>
    <div class="control-actions">
      <label>
        <span>Approval evidence</span>
        <input v-model="evidenceId" name="evidenceId" maxlength="128" autocomplete="off">
      </label>
      <button
        class="secondary-button"
        type="button"
        data-action="approve"
        :disabled="pending || !status.task_id || !evidenceId.trim()"
        @click="approve"
      >
        Approve
      </button>
      <button
        class="primary-button"
        type="button"
        data-action="launch"
        :disabled="pending || !status.task_id || status.terminal"
        @click="emit('launch')"
      >
        Launch workflow
      </button>
      <button
        v-if="status.run_id && !confirmingCancel"
        class="danger-button"
        type="button"
        data-action="cancel"
        :disabled="pending || status.terminal"
        @click="confirmingCancel = true"
      >
        Cancel run
      </button>
      <button
        v-else-if="status.run_id"
        class="danger-button"
        type="button"
        data-action="confirm-cancel"
        :disabled="pending || status.terminal"
        @click="emit('cancel'); confirmingCancel = false"
      >
        Confirm cancellation
      </button>
    </div>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
  </section>
</template>
