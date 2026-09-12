<script setup lang="ts">const route = useRoute(); const identifier = computed(() => String(route.params.id))</script>
<template><ResourceDetailView title="Task detail" description="Assignment, state history and evidence for one task." icon="i-lucide-list-checks" resource="tasks" :identifier="identifier" /></template>
