export interface SlideData {
  slide_index: number
  question_number: number | null
  question: string
  alternatives: string[]
  correct_answer: string | null
}

export interface AnalyzeResult {
  job_id: string
  pptx_path: string
  slides: SlideData[]
}

export interface ProcessResult {
  process_job_id: string
}

export interface JobStatus {
  job_id: string
  status: 'pending' | 'running' | 'done' | 'error'
  codes?: string[]
  error?: string
}

export interface AuthStatus {
  has_session: boolean
}
