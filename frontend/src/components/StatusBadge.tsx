import type { MatchStatus, ProcessingStage } from '../api/types'
import { stageLabel } from '../lib/stages'
import { Badge, Spinner } from './ui/primitives'

export function StatusBadge({
  status,
  stage,
}: {
  status: MatchStatus
  stage?: ProcessingStage | null
}) {
  switch (status) {
    case 'completed':
      return <Badge tone="good">Completed</Badge>
    case 'failed':
      return <Badge tone="bad">Failed</Badge>
    case 'cancelled':
      return <Badge tone="neutral">Cancelled</Badge>
    case 'processing':
      return (
        <Badge tone="info">
          <Spinner />
          {stage ? stageLabel(stage) : 'Processing'}
        </Badge>
      )
    case 'queued':
      return <Badge tone="info">Queued</Badge>
    default:
      return <Badge tone="neutral">Uploaded</Badge>
  }
}
