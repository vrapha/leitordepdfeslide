import { useEffect, useRef, useState } from 'react'
import { Download, Play, LogIn, FileText } from 'lucide-react'
import FileUpload from '../components/FileUpload'
import LogViewer from '../components/LogViewer'
import {
  extractPdf,
  getPdfResult,
  downloadCsv,
  pdfWsUrl,
  getSiteStatus,
  startSiteLogin,
} from '../api/client'

type Stage = 'idle' | 'running' | 'done' | 'error'

export default function PDFPage() {
  const [stage, setStage] = useState<Stage>('idle')
  const [file, setFile] = useState<File | null>(null)
  const [target, setTarget] = useState(30)
  const [jobId, setJobId] = useState('')
  const [codes, setCodes] = useState<string[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [hasSiteSession, setHasSiteSession] = useState(false)
  const [loginLoading, setLoginLoading] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    getSiteStatus().then(r => setHasSiteSession(r.has_session))
  }, [])

  function addLog(msg: string) {
    setLogs(prev => [...prev, msg])
  }

  async function handleExtract() {
    if (!file) return
    setLogs([])
    setCodes([])
    setStage('running')
    try {
      addLog('[INFO] Enviando PDF para extração...')
      const result = await extractPdf(file, target)
      setJobId(result.job_id)

      const ws = new WebSocket(pdfWsUrl(result.job_id))
      wsRef.current = ws
      ws.onmessage = async e => {
        const msg: string = e.data
        if (msg.startsWith('__STATUS__')) {
          const status = msg.replace('__STATUS__', '')
          ws.close()
          if (status === 'done') {
            const r = await getPdfResult(result.job_id)
            setCodes(r.codes || [])
            setStage('done')
          } else {
            setStage('error')
          }
        } else {
          addLog(msg)
        }
      }
      ws.onerror = () => addLog('[ERROR] Erro na conexão WebSocket')
    } catch (e: any) {
      addLog(`[ERROR] ${e.message}`)
      setStage('error')
    }
  }

  async function handleLogin() {
    setLoginLoading(true)
    addLog('[INFO] Abrindo browser para login no painel...')
    try {
      const r = await startSiteLogin()
      addLog(`[INFO] ${r.message}`)
      const interval = setInterval(async () => {
        const status = await fetch(`/api/auth/login/status/${r.job_id}`).then(x => x.json())
        if (status.status === 'done') {
          clearInterval(interval)
          setHasSiteSession(true)
          addLog('[SUCCESS] Login realizado e sessão salva!')
          setLoginLoading(false)
        } else if (status.status === 'error') {
          clearInterval(interval)
          addLog(`[ERROR] Falha no login: ${status.error}`)
          setLoginLoading(false)
        }
      }, 3000)
    } catch (e: any) {
      addLog(`[ERROR] ${e.message}`)
      setLoginLoading(false)
    }
  }

  const isRunning = stage === 'running'

  return (
    <div className="space-y-6">
      {/* Título */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Leitor de PDF</h1>
        <p className="text-gray-500 text-sm mt-1">
          Extrai questões de PDFs acadêmicos e encontra os códigos correspondentes no painel EMR.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Painel esquerdo */}
        <div className="space-y-4">
          {/* Upload */}
          <div className="card">
            <h2 className="font-semibold mb-3 text-gray-800">1. Arquivo PDF</h2>
            <FileUpload
              accept=".pdf"
              label="Selecione o arquivo PDF"
              onFile={setFile}
              disabled={isRunning}
            />
          </div>

          {/* Target */}
          <div className="card">
            <h2 className="font-semibold mb-3 text-gray-800">2. Meta de códigos</h2>
            <input
              type="number"
              min={1}
              max={200}
              className="input"
              value={target}
              onChange={e => setTarget(Number(e.target.value))}
              disabled={isRunning}
            />
            <p className="text-xs text-gray-400 mt-1">
              Número máximo de questões a encontrar.
            </p>
          </div>

          {/* Sessão painel */}
          <div className="card">
            <h2 className="font-semibold mb-3 text-gray-800">Sessão Painel</h2>
            <div className={`text-xs mb-3 px-3 py-2 rounded-lg ${hasSiteSession ? 'bg-green-50 text-green-700' : 'bg-yellow-50 text-yellow-700'}`}>
              {hasSiteSession ? '✓ Sessão salva encontrada' : '⚠ Sem sessão. Faça login antes de extrair.'}
            </div>
            <button
              className="btn-secondary w-full flex items-center justify-center gap-2 text-sm"
              onClick={handleLogin}
              disabled={loginLoading || isRunning}
            >
              <LogIn size={15} />
              {loginLoading ? 'Aguardando login...' : 'Login Painel'}
            </button>
          </div>

          {/* Ação */}
          <div className="space-y-2">
            <button
              className="btn-primary w-full flex items-center justify-center gap-2"
              onClick={handleExtract}
              disabled={!file || isRunning}
            >
              <Play size={16} className={isRunning ? 'animate-pulse' : ''} />
              {isRunning ? 'Extraindo...' : 'Extrair Questões'}
            </button>

            {stage === 'done' && jobId && (
              <button
                className="btn-secondary w-full flex items-center justify-center gap-2"
                onClick={() => downloadCsv(jobId)}
              >
                <Download size={16} />
                Baixar CSV
              </button>
            )}
          </div>
        </div>

        {/* Painel direito */}
        <div className="lg:col-span-2 space-y-4">
          {/* Códigos extraídos */}
          {codes.length > 0 && (
            <div className="card">
              <div className="flex items-center gap-2 mb-3">
                <FileText size={18} className="text-emr-green" />
                <h2 className="font-semibold text-gray-800">
                  Códigos extraídos — {codes.length} resultado{codes.length !== 1 ? 's' : ''}
                </h2>
              </div>
              <div className="bg-gray-50 rounded-lg p-4 font-mono text-sm max-h-80 overflow-y-auto space-y-1">
                {codes.map((code, i) => (
                  <div
                    key={i}
                    className={`${
                      code.includes('NÃO ENCONTRADA')
                        ? 'text-red-500'
                        : 'text-gray-800'
                    }`}
                  >
                    {i + 1}. {code}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Log */}
          <div className="card p-0 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="font-semibold text-gray-800">Log</h2>
            </div>
            <LogViewer logs={logs} className="h-80 rounded-none rounded-b-xl" />
          </div>
        </div>
      </div>
    </div>
  )
}
