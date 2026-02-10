import { Button } from './Button'

interface PaginationProps {
  currentPage: number
  totalPages: number
  totalItems: number
  onPageChange: (page: number) => void
}

export function Pagination({
  currentPage,
  totalPages,
  totalItems,
  onPageChange,
}: PaginationProps) {
  const hasPrev = currentPage > 1
  const hasNext = currentPage < totalPages

  return (
    <div className="mx-pagination">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={!hasPrev}
      >
        Previous
      </Button>

      <span className="mx-pagination__info">
        Page {currentPage} of {totalPages} ({totalItems} items)
      </span>

      <Button
        variant="secondary"
        size="sm"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={!hasNext}
      >
        Next
      </Button>
    </div>
  )
}
