import { useEffect, useState } from 'react'
import { X, AlertCircle, CheckCircle, Info } from 'lucide-react'

export type ToastType = 'success' | 'error' | 'info'

interface ToastProps {
  message: string
  type: ToastType
  onClose: () => void
  duration?: number
}

export function Toast({ message, type, onClose, duration = 5000 }: ToastProps) {
  const [isVisible, setIsVisible] = useState(true)

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsVisible(false)
      setTimeout(onClose, 300)
    }, duration)

    return () => clearTimeout(timer)
  }, [duration, onClose])

  const config = {
    success: {
      icon: <CheckCircle className="w-5 h-5" />,
      gradient: 'from-emerald-500 to-teal-500',
      border: 'border-emerald-500/30',
      bg: 'from-emerald-900/80 to-teal-900/80',
      text: 'text-emerald-300',
    },
    error: {
      icon: <AlertCircle className="w-5 h-5" />,
      gradient: 'from-red-500 to-rose-500',
      border: 'border-red-500/30',
      bg: 'from-red-900/80 to-rose-900/80',
      text: 'text-red-300',
    },
    info: {
      icon: <Info className="w-5 h-5" />,
      gradient: 'from-orange-500 to-amber-500',
      border: 'border-orange-500/30',
      bg: 'from-orange-900/80 to-amber-900/80',
      text: 'text-orange-300',
    },
  }

  const { icon, gradient, border, bg, text } = config[type]

  return (
    <div
      className={`
        flex items-center gap-4 px-5 py-4 rounded-2xl border backdrop-blur-xl
        shadow-2xl transition-all duration-300
        bg-gradient-to-r ${bg} ${border}
        ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}
      `}
    >
      <div className={`p-2 rounded-xl bg-gradient-to-br ${gradient}`}>
        {icon}
      </div>
      <span className={`text-sm font-medium ${text}`}>{message}</span>
      <button
        onClick={() => {
          setIsVisible(false)
          setTimeout(onClose, 300)
        }}
        className="text-stone-400 hover:text-white transition-colors p-1 hover:bg-white/10 rounded-lg"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

interface ToastItem {
  id: string
  message: string
  type: ToastType
}

interface ToastContainerProps {
  toasts: ToastItem[]
  removeToast: (id: string) => void
}

export function ToastContainer({ toasts, removeToast }: ToastContainerProps) {
  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-3">
      {toasts.map((toast) => (
        <Toast
          key={toast.id}
          message={toast.message}
          type={toast.type}
          onClose={() => removeToast(toast.id)}
        />
      ))}
    </div>
  )
}
