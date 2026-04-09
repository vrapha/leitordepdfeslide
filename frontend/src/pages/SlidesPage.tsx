import { useEffect, useRef, useState } from 'react'
import { Download, Play, RefreshCw, Square, LogIn } from 'lucide-react'
import FileUpload from '../components/FileUpload'
import ResultsTable from '../components/ResultsTable'
import LogViewer from '../components/LogViewer'
import {
  analyzeSlides,
  processSlides,
  downloadSlides,
  slidesWsUrl,
  getChatGptStatus,
  startChatGptLogin,
} from '../api/client'
import { SlideData } from '../types'

type Stage = 'idle' | 'analyzing' | 'analyzed' | 'processing' | 'done' | 'error'

export default function SlidesPage() {
  const [stage, setStage] = useState<Stage>('idle')
  const [file, setFile] = useState<File | null>(null)
  const [gabarito, setGabarito] = useState('')
  const [startQuestion, setStartQuestion] = useState(1)
  const [slides, setSlides] = useState<SlideData[]>([])
  const [analyzeJobId, setAnalyzeJobId] = useState('')
  const [processJobId, setProcessJobId] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const [hasChatSession, setHasChatSession] = useState(false)
  const [loginLoading, setLoginLoading] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const stopRef = useRef(false)

  useEffect(() => {
    getChatGptStatus().then(r => setHasChatSession(r.has_session))
  }, [])

  function addLog(msg: string) {
    setLogs(prev => [...prev, msg])
  }

  function connectWs(url: string, onDone?: (status: string) => void) {
    const ws = new WebSocket(url)
    wsRef.current = ws
    ws.onmessage = e => {
      const msg: string = e.data
      if (msg.startsWith('__STATUS__')) {
        onDone?.(msg.replace('__STATUS__', ''))
        ws.close()
      } else {
        addLog(msg)
      }
    }
    ws.onerror = () => addLog('[ERROR] Erro na conexão WebSocket')
    return ws
  }

  async function handleAnalyze() {
    if (!file) return
    setLogs([])
    setStage('analyzing')
    stopRef.current = false
    try {
      addLog('[INFO] Enviando arquivo para análise...')
      const result = await analyzeSlides(file, gabarito)
      if (result.error) throw new Error(result.error)
      setAnalyzeJobId(result.job_id)
      setSlides(result.slides)
      setStage('analyzed')
      addLog(`[SUCCESS] ${result.slides.length} slides analisados com sucesso!`)
    } catch (e: any) {
      addLog(`[ERROR] ${e.message}`)
      setStage('error')
    }
  }

  async function handleProcess() {
    if (!analyzeJobId || slides.length === 0) return
    setLogs([])
    setStage('processing')
    stopRef.current = false
    try {
      addLog('[INFO] Iniciando automação ChatGPT...')
      const result = await processSlides(analyzeJobId, slides, startQuestion)
      setProcessJobId(result.process_job_id)

      connectWs(slidesWsUrl(result.process_job_id), status => {
        setStage(status === 'done' ? 'done' : 'error')
      })
    } catch (e: any) {
      addLog(`[ERROR] ${e.message}`)
      setStage('error')
    }
  }

  function handleStop() {
    stopRef.current = true
    wsRef.current?.close()
    addLog('[INFO] Processo interrompido pelo usuário.')
    setStage('analyzed')
  }

  async function handleLogin() {
    setLoginLoading(true)
    addLog('[INFO] Abrindo browser para login no ChatGPT...')
    try {
      const r = await startChatGptLogin()
      addLog(`[INFO] ${r.message}`)
      // Poll status
      const interval = setInterval(async () => {
        const status = await fetch(`/api/auth/login/status/${r.job_id}`).then(x => x.json())
        if (status.status === 'done') {
          clearInterval(interval)
          setHasChatSession(true)
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

  const isRunning = stage === 'analyzing' || stage === 'processing'
  const detectedCount = slides.filter(s => s.correct_answer).length

  return (
    <div className="space-y-6">
      {/* Título */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Leitor de Slides</h1>
        <p className="text-gray-500 text-sm mt-1">
          Analisa apresentações PPTX com questões médicas, detecta gabaritos e gera comentários via ChatGPT.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Painel esquerdo: configurações */}
        <div className="space-y-4">
          {/* Upload */}
          <div className="card">
            <h2 className="font-semibold mb-3 text-gray-800">1. Arquivo PPTX</h2>
            <FileUpload
              accept=".pptx"
              label="Selecione o arquivo PPTX"
              onFile={setFile}
              disabled={isRunning}
            />
          </div>

          {/* Gabarito manual */}
          <div className="card">
            <h2 className="font-semibold mb-3 text-gray-800">2. Gabarito manual (opcional)</h2>
            <textarea
              className="input h-28 resize-none font-mono text-xs"
              placeholder="Ex:&#10;Q1. A&#10;Q2. C&#10;Q3. B&#10;&#10;Ou apenas:&#10;A&#10;C&#10;B"
              value={gabarito}
              onChange={e => setGabarito(e.target.value)}
              disabled={isRunning}
            />
          </div>

          {/* Questão inicial */}
          <div className="card">
            <h2 className="font-semibold mb-3 text-gray-800">3. Iniciar da questão</h2>
            <input
              type="number"
              min={1}
              className="input"
              value={startQuestion}
              onChange={e => setStartQuestion(Number(e.target.value))}
              disabled={isRunning}
            />
          </div>

          {/* Sessão ChatGPT */}
          <div className="card">
            <h2 className="font-semibold mb-3 text-gray-800">Sessão ChatGPT</h2>
            <div className={`text-xs mb-3 px-3 py-2 rounded-lg ${hasChatSession ? 'bg-green-50 text-green-700' : 'bg-yellow-50 text-yellow-700'}`}>
              {hasChatSession ? '✓ Sessão salva encontrada' : '⚠ Sem sessão. Faça login antes de processar.'}
            </div>
            <button
              className="btn-secondary w-full flex items-center justify-center gap-2 text-sm"
              onClick={handleLogin}
              disabled={loginLoading || isRunning}
            >
              <LogIn size={15} />
              {loginLoading ? 'Aguardando login...' : 'Login ChatGPT'}
            </button>
          </div>

          {/* Botões de ação */}
          <div className="space-y-2">
            <button
              className="btn-primary w-full flex items-center justify-center gap-2"
              onClick={handleAnalyze}
              disabled={!file || isRunning}
            >
              <RefreshCw size={16} className={stage === 'analyzing' ? 'animate-spin' : ''} />
              {stage === 'analyzing' ? 'Analisando...' : '1. Analisar Slides'}
            </button>

            <button
              className="btn-primary w-full flex items-center justify-center gap-2"
              style={{ backgroundColor: '#1a5c8f' }}
              onClick={handleProcess}
              disabled={stage !== 'analyzed' || slides.length === 0}
            >
              <Play size={16} />
              2. Iniciar Automação (Bot)
            </button>

            {stage === 'processing' && (
              <button
                className="btn-danger w-full flex items-center justify-center gap-2"
                onClick={handleStop}
              >
                <Square size={16} />
                Parar
              </button>
            )}

            {stage === 'done' && processJobId && (
              <button
                className="btn-secondary w-full flex items-center justify-center gap-2"
                onClick={() => downloadSlides(processJobId)}
              >
                <Download size={16} />
                Baixar PPTX Processado
              </button>
            )}
          </div>
        </div>

        {/* Painel direito: tabela + logs */}
        <div className="lg:col-span-2 space-y-4">
          {slides.length > 0 && (
            <div className="card p-0 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
                <h2 className="font-semibold text-gray-800">
                  Resultados — {slides.length} slides, {detectedCount} com resposta
                </h2>
              </div>
              <div className="p-4">
                <ResultsTable
                  slides={slides}
                  onChange={setSlides}
                  disabled={isRunning}
                />
              </div>
            </div>
          )}

          <div className="card p-0 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="font-semibold text-gray-800">Log</h2>
            </div>
            <LogViewer logs={logs} className="h-64 rounded-none rounded-b-xl" />
          </div>
        </div>
      </div>
    </div>
  )
}
