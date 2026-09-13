import { defineConfig } from 'orval'

export default defineConfig({
  dashboard: {
    input: {
      target: './openapi/dashboard.json',
    },
    output: {
      target: './app/api/generated/dashboard.ts',
      schemas: './app/api/generated/models',
      client: 'vue-query',
      httpClient: 'fetch',
      clean: true,
      override: {
        fetch: {
          includeHttpResponseReturnType: false,
        },
        mutator: {
          path: './app/api/backend-fetcher.ts',
          name: 'backendFetch',
        },
      },
    },
  },
})
