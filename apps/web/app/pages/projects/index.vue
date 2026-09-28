<template>
  <div class="page-stack">
    <PageHeading
      title="Projects"
      description="Portfolio, milestones and delivery state from the authoritative backend."
      icon="i-lucide-panels-top-left"
    >
      <NuxtLink class="primary-button" to="/projects/new">
        <UIcon name="i-lucide-plus" aria-hidden="true" /> New project
      </NuxtLink>
    </PageHeading>
    <ProjectCollectionView :show-heading="false" />
  </div>
</template>
