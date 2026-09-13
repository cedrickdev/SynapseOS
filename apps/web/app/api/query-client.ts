import { QueryClient } from '@tanstack/vue-query'

export function createDashboardQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 15_000,
        gcTime: 300_000,
        refetchOnWindowFocus: false,
      },
    },
  })
}
