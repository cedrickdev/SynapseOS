<script setup lang="ts">
import { ref } from 'vue'

interface IntakeAgent {
  readonly id: string
  readonly name: string
  readonly role: string
}

interface IntakeDraft {
  readonly name: string
  readonly specification: string
  readonly taskTitle: string
  readonly agentId: string
}

const props = defineProps<{
  agents: readonly IntakeAgent[]
  pending: boolean
  error?: string | undefined
}>()
const emit = defineEmits<{ submit: [draft: IntakeDraft] }>()

const name = ref('')
const specification = ref('')
const taskTitle = ref('')
const agentId = ref('')

function submit(): void {
  const draft = {
    name: name.value.trim(),
    specification: specification.value.trim(),
    taskTitle: taskTitle.value.trim(),
    agentId: agentId.value,
  }
  if (!draft.name || !draft.specification || !draft.taskTitle || !draft.agentId || props.pending) {
    return
  }
  emit('submit', draft)
}
</script>

<template>
  <form class="control-form" @submit.prevent="submit">
    <label>
      <span>Project name</span>
      <input v-model="name" name="name" maxlength="255" required autocomplete="off">
    </label>
    <label>
      <span>Initial task</span>
      <input v-model="taskTitle" name="taskTitle" maxlength="500" required autocomplete="off">
    </label>
    <label>
      <span>Assigned agent</span>
      <select v-model="agentId" name="agentId" required>
        <option value="" disabled>Select an available agent</option>
        <option v-for="agent in agents" :key="agent.id" :value="agent.id">
          {{ agent.name }} — {{ agent.role }}
        </option>
      </select>
    </label>
    <label class="form-span">
      <span>Specification</span>
      <textarea v-model="specification" name="specification" maxlength="16384" rows="10" required />
    </label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <div class="form-actions form-span">
      <NuxtLink class="secondary-button" to="/projects">Cancel</NuxtLink>
      <button class="primary-button" type="submit" :disabled="pending || agents.length === 0">
        {{ pending ? 'Creating project…' : 'Create project' }}
      </button>
    </div>
  </form>
</template>
