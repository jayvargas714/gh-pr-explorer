import { useReviewStore } from '../../stores/useReviewStore'
import { Modal } from '../common/Modal'
import { Alert } from '../common/Alert'

export function ReviewErrorModal() {
  const { reviewErrorModal, setReviewErrorModal } = useReviewStore()

  if (!reviewErrorModal.show) return null

  const handleClose = () => {
    setReviewErrorModal({
      show: false,
      prNumber: null,
      prTitle: '',
      errorOutput: '',
      exitCode: null,
    })
  }

  return (
    <Modal title={`Review Failed - PR #${reviewErrorModal.prNumber}`} onClose={handleClose} size="lg">
      <Alert variant="error">
        <strong>Review process failed</strong>
        {reviewErrorModal.exitCode !== null && <> (exit code: {reviewErrorModal.exitCode})</>}
      </Alert>

      <div className="mx-review-error__details">
        <h3>PR Details</h3>
        <p>{reviewErrorModal.prTitle}</p>

        <h3>Error Output</h3>
        <pre className="mx-review-error__output">{reviewErrorModal.errorOutput || 'No error output available'}</pre>

        <p className="mx-review-error__help">
          This usually means the Claude CLI encountered an issue. Check the error output above for
          details, or try running the review again.
        </p>
      </div>
    </Modal>
  )
}
