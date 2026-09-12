interface MetricSeries {
  name: string
  labels: unknown[]
  value: number
}

interface MetricsSnapshot {
  counters: MetricSeries[]
  histograms: MetricSeries[]
  gauges: MetricSeries[]
}

export interface MetricsSummary {
  counters: number
  histograms: number
  gauges: number
  totalSeries: number
}

function isMetricSeries(value: unknown): value is MetricSeries {
  if (typeof value !== 'object' || value === null) {
    return false
  }

  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.name === 'string'
    && Array.isArray(candidate.labels)
    && typeof candidate.value === 'number'
    && Number.isFinite(candidate.value)
  )
}

function isMetricSeriesList(value: unknown): value is MetricSeries[] {
  return Array.isArray(value) && value.every(isMetricSeries)
}

export function summarizeMetrics(payload: unknown): MetricsSummary | null {
  if (typeof payload !== 'object' || payload === null) {
    return null
  }

  const snapshot = payload as Partial<MetricsSnapshot>
  if (
    !isMetricSeriesList(snapshot.counters)
    || !isMetricSeriesList(snapshot.histograms)
    || !isMetricSeriesList(snapshot.gauges)
  ) {
    return null
  }

  const counters = snapshot.counters.length
  const histograms = snapshot.histograms.length
  const gauges = snapshot.gauges.length

  return {
    counters,
    histograms,
    gauges,
    totalSeries: counters + histograms + gauges,
  }
}
