import { useState } from 'react'
import { clsx } from 'clsx'
import { SlideData } from '../types'

interface Props {
  slides: SlideData[]
  onChange: (updated: SlideData[]) => void
  disabled?: boolean
}

const VALID_ANSWERS = ['A', 'B', 'C', 'D', 'E', 'ANULADA']

export default function ResultsTable({ slides, onChange, disabled }: Props) {
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')

  function startEdit(idx: number, current: string) {
    if (disabled) return
    setEditingIdx(idx)
    setEditValue(current || '')
  }

  function commitEdit(idx: number) {
    const val = editValue.trim().toUpperCase()
    if (!VALID_ANSWERS.includes(val) && val !== '') {
      alert('Resposta inválida. Use A, B, C, D, E ou ANULADA.')
      return
    }
    const updated = slides.map((s, i) =>
      i === idx ? { ...s, correct_answer: val || null } : s
    )
    onChange(updated)
    setEditingIdx(null)
  }

  function markAnnulled(idx: number) {
    const updated = slides.map((s, i) =>
      i === idx ? { ...s, correct_answer: 'ANULADA' } : s
    )
    onChange(updated)
  }

  function clearAnswer(idx: number) {
    const updated = slides.map((s, i) =>
      i === idx ? { ...s, correct_answer: null } : s
    )
    onChange(updated)
  }

  if (slides.length === 0) {
    return (
      <div className="text-center py-12 text-gray-400">
        Nenhum slide analisado ainda. Carregue um arquivo PPTX e clique em Analisar.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-emr-green text-white text-left">
            <th className="px-4 py-3 w-16">Slide</th>
            <th className="px-4 py-3 w-16">Q.</th>
            <th className="px-4 py-3 w-24">Resposta</th>
            <th className="px-4 py-3">Questão</th>
            <th className="px-4 py-3 w-32">Ações</th>
          </tr>
        </thead>
        <tbody>
          {slides.map((slide, i) => (
            <tr
              key={i}
              className={clsx(
                'border-t border-gray-100 hover:bg-gray-50 transition-colors',
                slide.correct_answer === 'ANULADA' && 'bg-red-50'
              )}
            >
              <td className="px-4 py-2 text-gray-500">{slide.slide_index + 1}</td>
              <td className="px-4 py-2 font-medium">{slide.question_number ?? '—'}</td>
              <td className="px-4 py-2">
                {editingIdx === i ? (
                  <input
                    autoFocus
                    className="w-20 border border-emr-green rounded px-2 py-1 text-center uppercase text-sm"
                    value={editValue}
                    onChange={e => setEditValue(e.target.value)}
                    onBlur={() => commitEdit(i)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') commitEdit(i)
                      if (e.key === 'Escape') setEditingIdx(null)
                    }}
                  />
                ) : (
                  <span
                    className={clsx(
                      'inline-block px-3 py-1 rounded-full text-xs font-bold cursor-pointer',
                      slide.correct_answer === 'ANULADA'
                        ? 'bg-red-100 text-red-700'
                        : slide.correct_answer
                        ? 'bg-green-100 text-green-700'
                        : 'bg-gray-100 text-gray-400'
                    )}
                    title="Clique para editar"
                    onDoubleClick={() => startEdit(i, slide.correct_answer || '')}
                  >
                    {slide.correct_answer || '—'}
                  </span>
                )}
              </td>
              <td className="px-4 py-2 text-gray-700 max-w-md">
                <p className="truncate">{slide.question || '(sem texto)'}</p>
                {slide.alternatives.length > 0 && (
                  <p className="text-xs text-gray-400 mt-0.5">
                    {slide.alternatives.length} alternativas
                  </p>
                )}
              </td>
              <td className="px-4 py-2">
                <div className="flex gap-1">
                  <button
                    className="text-xs px-2 py-1 rounded bg-red-100 text-red-600 hover:bg-red-200 disabled:opacity-40"
                    disabled={disabled}
                    onClick={() => markAnnulled(i)}
                    title="Marcar como anulada"
                  >
                    Anulada
                  </button>
                  <button
                    className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-500 hover:bg-gray-200 disabled:opacity-40"
                    disabled={disabled}
                    onClick={() => clearAnswer(i)}
                    title="Limpar resposta"
                  >
                    Limpar
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
