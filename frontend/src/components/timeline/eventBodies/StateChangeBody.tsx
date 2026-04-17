import type {
  ClosedEvent,
  ReopenedEvent,
  MergedEvent,
  ReadyForReviewEvent,
  ConvertToDraftEvent,
  OpenedEvent,
} from '../../../api/types'

type AnyStateEvent =
  | OpenedEvent | ClosedEvent | ReopenedEvent | MergedEvent
  | ReadyForReviewEvent | ConvertToDraftEvent

interface Props { event: AnyStateEvent }

const LABEL: Record<AnyStateEvent['type'], string> = {
  opened: 'Opened this pull request',
  closed: 'Closed this pull request',
  reopened: 'Reopened this pull request',
  merged: 'Merged',
  ready_for_review: 'Marked ready for review',
  convert_to_draft: 'Converted back to draft',
}

export function StateChangeBody({ event }: Props) {
  return <div>{LABEL[event.type]}</div>
}
