/** Human labels for the processing stages. Kept out of the component file so that
 *  module exports only components, which is what fast refresh needs. */

import type { ProcessingStage } from '../api/types'

const STAGE_LABELS: Record<ProcessingStage, string> = {
  validating: 'Validating',
  downloading: 'Downloading',
  parsing: 'Parsing demo',
  normalizing: 'Normalizing',
  computing: 'Computing statistics',
  persisting: 'Saving',
}

export const STAGE_ORDER: ProcessingStage[] = [
  'validating',
  'downloading',
  'parsing',
  'computing',
  'persisting',
]

export function stageLabel(stage: ProcessingStage | null): string {
  return stage ? STAGE_LABELS[stage] : 'Waiting'
}
