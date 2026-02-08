import { ReactNode } from 'react'

export interface Column<T> {
  key: string
  label: string
  sortable?: boolean
  tooltip?: string
  render?: (item: T) => ReactNode
}

interface SortableTableProps<T> {
  columns: Column<T>[]
  data: T[]
  sortBy?: string
  sortDirection?: 'asc' | 'desc'
  onSort?: (column: string) => void
  keyExtractor: (item: T) => string | number
  className?: string
}

export function SortableTable<T>({
  columns,
  data,
  sortBy,
  sortDirection,
  onSort,
  keyExtractor,
  className = '',
}: SortableTableProps<T>) {
  const handleHeaderClick = (column: Column<T>) => {
    if (column.sortable && onSort) {
      onSort(column.key)
    }
  }

  const getSortIcon = (column: Column<T>) => {
    if (!column.sortable) return null
    if (sortBy !== column.key) return ' ⇅'
    return sortDirection === 'asc' ? ' ▲' : ' ▼'
  }

  return (
    <div className={`mx-table-wrapper ${className}`}>
      <table className="mx-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={column.sortable ? 'mx-table__header--sortable' : ''}
                onClick={() => handleHeaderClick(column)}
                title={column.tooltip}
              >
                {column.label}
                {getSortIcon(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item) => (
            <tr key={keyExtractor(item)}>
              {columns.map((column) => (
                <td key={column.key}>
                  {column.render
                    ? column.render(item)
                    : String((item as any)[column.key] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
