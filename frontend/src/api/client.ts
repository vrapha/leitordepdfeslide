const BASE_URL = import.meta.env.VITE_API_URL || ''

// ─────────────── Slides API ───────────────

export async function analyzeSlides(file: File, gabarito: string) {
  const form = new FormData()
  form.append('file', file)
  form.append('gabarito', gabarito)
  const res = await fetch(`${BASE_URL}/api/slides/analyze`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Erro ${res.status}: ${res.statusText}`)
  return res.json()
}

export async function processSlides(jobId: string, slidesData: object[], startQuestion: number) {
  const res = await fetch(`${BASE_URL}/api/slides/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, slides_data: slidesData, start_question: startQuestion }),
  })
  if (!res.ok) throw new Error(`Erro ${res.status}: ${res.statusText}`)
  return res.json()
}

export function downloadSlides(jobId: string) {
  window.open(`${BASE_URL}/api/slides/download/${jobId}`, '_blank')
}

export function slidesWsUrl(jobId: string): string {
  const base = (import.meta.env.VITE_API_URL || window.location.origin).replace(/^http/, 'ws')
  return `${base}/api/slides/ws/${jobId}`
}

// ─────────────── PDF API ───────────────

export async function extractPdf(file: File, target: number) {
  const form = new FormData()
  form.append('file', file)
  form.append('target', String(target))
  const res = await fetch(`${BASE_URL}/api/pdf/extract`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Erro ${res.status}: ${res.statusText}`)
  return res.json()
}

export async function getPdfResult(jobId: string) {
  const res = await fetch(`${BASE_URL}/api/pdf/result/${jobId}`)
  if (!res.ok) throw new Error(`Erro ${res.status}: ${res.statusText}`)
  return res.json()
}

export function downloadCsv(jobId: string) {
  window.open(`${BASE_URL}/api/pdf/download/${jobId}`, '_blank')
}

export function pdfWsUrl(jobId: string): string {
  const base = (import.meta.env.VITE_API_URL || window.location.origin).replace(/^http/, 'ws')
  return `${base}/api/pdf/ws/${jobId}`
}

// ─────────────── Auth API ───────────────

export async function getChatGptStatus() {
  const res = await fetch(`${BASE_URL}/api/auth/chatgpt/status`)
  return res.json()
}

export async function startChatGptLogin() {
  const res = await fetch(`${BASE_URL}/api/auth/chatgpt/login`, { method: 'POST' })
  return res.json()
}

export async function getSiteStatus() {
  const res = await fetch(`${BASE_URL}/api/auth/site/status`)
  return res.json()
}

export async function startSiteLogin() {
  const res = await fetch(`${BASE_URL}/api/auth/site/login`, { method: 'POST' })
  return res.json()
}

export async function getLoginStatus(jobId: string) {
  const res = await fetch(`${BASE_URL}/api/auth/login/status/${jobId}`)
  return res.json()
}
