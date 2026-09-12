<script setup lang="ts">const route = useRoute(); const identifier = computed(() => String(route.params.id))</script>
<template><ResourceDetailView title="Agent details" description="Role, capabilities, reputation evidence and current workload." icon="i-lucide-bot" resource="agents" :identifier="identifier" /></template>
