import { NavLink } from 'react-router-dom'
import { FilePresentation, FileText } from 'lucide-react'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-emr-green text-white shadow-md">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-4">
          <div className="font-bold text-xl tracking-wide">EMR</div>
          <div className="text-sm opacity-80">Eu Médico Residente</div>
          <div className="ml-4 h-6 border-l border-white/30" />
          <nav className="flex gap-1">
            <NavLink
              to="/slides"
              className={({ isActive }) =>
                `flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-white/20 text-white'
                    : 'text-white/80 hover:bg-white/10 hover:text-white'
                }`
              }
            >
              <FilePresentation size={16} />
              Leitor de Slides
            </NavLink>
            <NavLink
              to="/pdf"
              className={({ isActive }) =>
                `flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-white/20 text-white'
                    : 'text-white/80 hover:bg-white/10 hover:text-white'
                }`
              }
            >
              <FileText size={16} />
              Leitor de PDF
            </NavLink>
          </nav>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">{children}</main>

      {/* Footer */}
      <footer className="bg-emr-green-dark text-white/60 text-xs text-center py-2">
        EMR Web App — Eu Médico Residente
      </footer>
    </div>
  )
}
