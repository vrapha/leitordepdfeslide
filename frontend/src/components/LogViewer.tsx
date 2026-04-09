import { useEffect, useRef } from 'react'
import { clsx } from 'clsx'

interface Props {
  logs: string[]
  className?: string
}

export default function LogViewer({ logs, className }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  function colorClass(log: string) {
    if (log.includes('[ERROR]')) return 'text-red-400'
    if (log.includes('[SUCCESS]') || log.includes('CONCLUÍDO') || log.includes('salvo')) return 'text-green-400'
    if (log.includes('[Bot]')) return 'text-yellow-300'
    if (log.includes('ENCONTRADO')) return 'text-cyan-400'
    return 'text-gray-300'
  }

  return (
    <div
      className={clsx(
        'bg-gray-900 rounded-xl p-4 font-mono text-xs overflow-y-auto',
        className
      )}
    >
      {logs.length === 0 ? (
        <p className="text-gray-500">Aguardando logs...</p>
      ) : (
        logs.map((log, i) => (
          <div key={i} className={clsx('leading-5', colorClass(log))}>
            {log}
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  )
}
