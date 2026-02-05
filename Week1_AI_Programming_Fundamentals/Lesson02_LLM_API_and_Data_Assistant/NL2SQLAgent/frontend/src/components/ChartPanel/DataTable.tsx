import type { TableData } from '../../types'

interface DataTableProps {
  data: TableData
}

export function DataTable({ data }: DataTableProps) {
  const { columns, rows, raw } = data

  // 优先使用 raw 数据（原始行数据），如果没有则使用 rows
  const displayRows = raw && raw.length > 0 ? raw : rows.map(row => [row.name, row.value])
  
  if (displayRows.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        暂无数据
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse">
        <thead className="sticky top-0 bg-slate-800">
          <tr>
            {columns.map((col, idx) => (
              <th
                key={`${col}-${idx}`}
                className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-wider border-b border-slate-700"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {displayRows.map((row, rowIndex) => (
            <tr
              key={rowIndex}
              className="hover:bg-slate-800/50 transition-colors"
            >
              {Array.isArray(row) ? (
                // raw 数据格式：数组
                row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    className="px-4 py-3 text-sm text-slate-300 whitespace-nowrap"
                  >
                    {String(cell ?? '-')}
                  </td>
                ))
              ) : (
                // 对象格式的行数据
                columns.map((col, colIndex) => (
                  <td
                    key={colIndex}
                    className="px-4 py-3 text-sm text-slate-300 whitespace-nowrap"
                  >
                    {String((row as Record<string, unknown>)[col] ?? '-')}
                  </td>
                ))
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
