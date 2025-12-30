import { useEffect, useState } from 'react'

export function ErrorBanner({ message }: { message: string | null }) {
  const [dismissedMessage, setDismissedMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!message) return
    setDismissedMessage(null)
  }, [message])

  if (!message) return null
  if (dismissedMessage === message) return null

  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-rose-900 flex items-start justify-between gap-4">
      <div className="text-sm">{message}</div>
      <button
        type="button"
        className="text-sm font-medium text-rose-900/80 hover:text-rose-900"
        onClick={() => setDismissedMessage(message)}
      >
        Dismiss
      </button>
    </div>
  )
}
