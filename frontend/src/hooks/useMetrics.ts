/**
 * The metric registry, fetched once.
 *
 * The definitions come from the server rather than being duplicated here, so a tooltip
 * can never describe a metric differently from the code that computes it.
 */

import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { MetricDefinition, Metrics } from '../api/types'

let cache: Metrics | null = null
let inFlight: Promise<Metrics> | null = null

export function useMetrics(): {
  metrics: Metrics | null
  byKey: Record<string, MetricDefinition>
} {
  const [metrics, setMetrics] = useState<Metrics | null>(cache)

  useEffect(() => {
    if (cache) return
    inFlight ??= api.metrics()
    let active = true
    inFlight
      .then((result) => {
        cache = result
        if (active) setMetrics(result)
      })
      .catch(() => {
        // Tooltips are an enhancement; the tables still work without them.
        inFlight = null
      })
    return () => {
      active = false
    }
  }, [])

  const byKey: Record<string, MetricDefinition> = {}
  for (const definition of metrics?.player_metrics ?? []) byKey[definition.key] = definition
  return { metrics, byKey }
}
