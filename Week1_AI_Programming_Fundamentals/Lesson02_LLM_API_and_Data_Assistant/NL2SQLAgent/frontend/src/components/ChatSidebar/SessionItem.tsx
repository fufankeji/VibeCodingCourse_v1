import { MessageSquare, Trash2 } from 'lucide-react'
import type { Session } from '../../types'

interface SessionItemProps {
  session: Session
  isActive: boolean
  onSelect: () => void
  onDelete: () => void
}

export function SessionItem({ session, isActive, onSelect, onDelete }: SessionItemProps) {
  return (
    <div
      onClick={onSelect}
      className={`
        group flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer
        transition-all duration-200
        ${isActive
          ? 'bg-blue-500/20 text-blue-400'
          : 'hover:bg-slate-700/50 text-slate-300'
        }
      `}
    >
      <MessageSquare className="w-4 h-4 flex-shrink-0" />
      <span className="flex-1 truncate text-sm">{session.title}</span>
      <button
        onClick={(e) => {
          e.stopPropagation()
          onDelete()
        }}
        className={`
          p-1 rounded opacity-0 group-hover:opacity-100
          hover:bg-red-500/20 hover:text-red-400
          transition-all duration-200
        `}
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
