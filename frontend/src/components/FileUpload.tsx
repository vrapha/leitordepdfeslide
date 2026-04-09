import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { clsx } from 'clsx'

interface Props {
  accept: string
  label: string
  onFile: (file: File) => void
  disabled?: boolean
}

export default function FileUpload({ accept, label, onFile, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [fileName, setFileName] = useState<string | null>(null)

  function handleFile(file: File | null) {
    if (!file) return
    setFileName(file.name)
    onFile(file)
  }

  return (
    <div
      className={clsx(
        'border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors',
        dragging ? 'border-emr-green bg-green-50' : 'border-gray-300 hover:border-emr-green',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={e => {
        e.preventDefault()
        setDragging(false)
        if (!disabled) handleFile(e.dataTransfer.files[0])
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        disabled={disabled}
        onChange={e => handleFile(e.target.files?.[0] ?? null)}
      />
      <Upload className="mx-auto mb-2 text-gray-400" size={28} />
      {fileName ? (
        <p className="text-sm font-medium text-emr-green">{fileName}</p>
      ) : (
        <>
          <p className="text-sm font-medium text-gray-700">{label}</p>
          <p className="text-xs text-gray-400 mt-1">Clique ou arraste o arquivo aqui</p>
        </>
      )}
    </div>
  )
}
