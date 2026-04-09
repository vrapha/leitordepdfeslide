import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import SlidesPage from './pages/SlidesPage'
import PDFPage from './pages/PDFPage'

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/slides" replace />} />
          <Route path="/slides" element={<SlidesPage />} />
          <Route path="/pdf" element={<PDFPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
