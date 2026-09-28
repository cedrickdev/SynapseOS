<script setup lang="ts">
import type { WorkflowStatus } from '../../api/generated/models'

defineProps<{ status: WorkflowStatus }>()
</script>

<template>
  <section class="workflow-status-grid" aria-label="Workflow status">
    <article data-status="stage"><span>Current stage</span><strong>{{ status.current_stage }}</strong></article>
    <article><span>Project</span><strong>{{ status.project_status }}</strong></article>
    <article><span>Task</span><strong>{{ status.task_status ?? 'Not assigned' }}</strong></article>
    <article><span>Queue</span><strong>{{ status.queue_status ?? 'Not queued' }}</strong></article>
    <article data-status="agent"><span>Assigned agent</span><strong :title="status.assigned_agent_id ?? undefined">{{ status.assigned_agent_id ?? 'Unassigned' }}</strong></article>
    <article data-status="qa"><span>QA gate</span><strong>{{ status.qa_status ?? 'Pending' }}</strong></article>
    <article data-status="security"><span>Security gate</span><strong>{{ status.security_status ?? 'Pending' }}</strong></article>
    <article><span>Merge gate</span><strong>{{ status.merge_gate_status ?? 'Pending' }}</strong></article>
    <article><span>Human approval</span><strong>{{ status.human_approval ? 'Approved' : 'Required' }}</strong></article>
    <article data-status="cost"><span>Provider cost</span><strong>{{ status.provider_cost_total }}</strong></article>
    <article data-status="blockers"><span>Blockers</span><strong>{{ status.blockers.length ? status.blockers.join(', ') : 'None' }}</strong></article>
    <article><span>Outcome</span><strong>{{ status.terminal ? 'Terminal' : 'Active' }}</strong></article>
  </section>
</template>
