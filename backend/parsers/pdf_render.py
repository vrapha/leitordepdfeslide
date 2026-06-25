"""
Renderizador de PPTX → PDF compartilhado pelos parsers.

A detecção visual de resposta (ler qual alternativa está dentro do marcador
vermelho) depende de uma renderização fiel do slide. Este módulo gera o PDF
usando o renderizador disponível, em ordem de preferência:

  1. PowerPoint via COM (pywin32) — Windows, renderização idêntica ao que o
     usuário vê. É o mais preciso.
  2. LibreOffice headless (`soffice`/`libreoffice`) — fallback multiplataforma
     (ex.: servidor Linux).

O PDF é gravado ao lado do .pptx e reaproveitado enquanto for mais novo que o
arquivo de origem, evitando reconverter para cada parser.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

# Código do formato PDF no SaveAs do PowerPoint (ppSaveAsPDF)
_PP_SAVE_AS_PDF = 32


def _pdf_path_for(abs_ppt: str) -> str:
    return str(Path(abs_ppt).with_suffix(".pdf"))


def render_pptx_to_pdf(pptx_path: str, logger: Callable = print) -> str | None:
    """
    Converte o PPTX em PDF e retorna o caminho do PDF (ou None se não houver
    renderizador disponível). Reaproveita um PDF já gerado se ele for mais
    recente que o .pptx.
    """
    abs_ppt = str(Path(pptx_path).resolve())
    pdf_path = _pdf_path_for(abs_ppt)

    # Reaproveita o PDF em cache se ainda estiver válido
    try:
        if os.path.exists(pdf_path) and os.path.getmtime(pdf_path) >= os.path.getmtime(abs_ppt):
            return pdf_path
    except OSError:
        pass

    if os.name == "nt" and _render_with_powerpoint(abs_ppt, pdf_path, logger):
        return pdf_path
    if _render_with_libreoffice(abs_ppt, pdf_path, logger):
        return pdf_path
    return None


def _render_with_powerpoint(abs_ppt: str, pdf_path: str, logger: Callable) -> bool:
    """Renderiza via PowerPoint COM. Requer Windows + pywin32 + PowerPoint."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False

    # win32com em thread de trabalho exige inicializar o COM nessa thread
    pythoncom.CoInitialize()
    powerpoint = None
    presentation = None
    try:
        powerpoint = win32com.client.DispatchEx("PowerPoint.Application")
        presentation = powerpoint.Presentations.Open(
            abs_ppt, ReadOnly=True, WithWindow=False
        )
        presentation.SaveAs(pdf_path, _PP_SAVE_AS_PDF)
        if os.path.exists(pdf_path):
            logger("[render] PDF gerado via PowerPoint.")
            return True
        return False
    except Exception as e:
        logger(f"[render] PowerPoint indisponível/falhou: {e}")
        return False
    finally:
        try:
            if presentation is not None:
                presentation.Close()
        except Exception:
            pass
        try:
            if powerpoint is not None:
                powerpoint.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


def _render_with_libreoffice(abs_ppt: str, pdf_path: str, logger: Callable) -> bool:
    """Renderiza via LibreOffice headless. Funciona em Linux/Windows se instalado."""
    out_dir = str(Path(abs_ppt).parent)
    for binary in ("soffice", "libreoffice"):
        try:
            result = subprocess.run(
                [binary, "--headless", "--convert-to", "pdf", "--outdir", out_dir, abs_ppt],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and os.path.exists(pdf_path):
                logger("[render] PDF gerado via LibreOffice.")
                return True
        except FileNotFoundError:
            continue
        except Exception as e:
            logger(f"[render] LibreOffice falhou: {e}")
    return False
