"""
EMR Web App — FastAPI Backend
Dois módulos: Leitor de Slides (PPTX) e Leitor de PDF (extração de códigos).
"""
import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from fastapi.responses import FileResponse
from routers import slides, pdf, auth
from routers import docx_router
from routers import extractor_router
from services.job_manager import get_job, cancel_job

# Produção = API_SECRET_KEY está definida no Railway
_is_production = bool(os.environ.get("API_SECRET_KEY", ""))

# Em produção, defina ALLOWED_ORIGIN no Railway com o domínio do Lovable.
_raw_origins = os.environ.get("ALLOWED_ORIGIN", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

# Em produção com wildcard: bloqueia CORS totalmente
if _is_production and "*" in ALLOWED_ORIGINS:
    print(
        "AVISO: ALLOWED_ORIGIN não configurado. CORS bloqueado.",
        file=sys.stderr,
    )
    ALLOWED_ORIGINS = []

app = FastAPI(
    title="EMR Web App",
    version="1.0.0",
    # Docs/schema sempre ocultos — nunca expor em produção
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(slides.router, prefix="/api/slides", tags=["slides"])
app.include_router(pdf.router, prefix="/api/pdf", tags=["pdf"])
app.include_router(docx_router.router, prefix="/api/docx", tags=["docx"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(extractor_router.router, prefix="/api/extractor", tags=["extractor"])


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/api/slides/download/{job_id}")
def download_pptx(job_id: str):
    """
    Download do PPTX processado — sem API key (job_id UUID é auth suficiente).
    Rota pública para permitir download direto sem passar pelo proxy do Lovable.
    """
    job = get_job(job_id)
    if not job or not job.result:
        return {"error": "Job não encontrado"}
    output_file = job.result.get("output_file")
    if not output_file or not Path(output_file).exists():
        return {"error": "Arquivo não encontrado"}
    return FileResponse(
        path=output_file,
        filename=Path(output_file).name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f"attachment; filename=\"{Path(output_file).name}\""},
    )


@app.get("/api/docx/status/{job_id}")
def docx_job_status(job_id: str):
    """Polling de status do job DOCX — sem API key."""
    job = get_job(job_id)
    if not job:
        return {"status": "not_found", "logs": [], "error": "Job não encontrado"}
    result = job.result or {}
    return {
        "status": job.status,
        "logs": job.logs,
        "error": job.error,
        "result": {
            "codes": result.get("codes", []),
            "principais": result.get("principais", []),
            "reservas": result.get("reservas", []),
        } if result else None,
    }


@app.get("/api/pdf/status/{job_id}")
def pdf_job_status(job_id: str):
    """
    Polling de status do job PDF — sem API key (job_id UUID é auth suficiente).
    """
    job = get_job(job_id)
    if not job:
        return {"status": "not_found", "logs": [], "error": "Job não encontrado"}
    codes = job.result.get("codes", []) if job.result else []
    return {
        "status": job.status,
        "logs": job.logs,
        "error": job.error,
        "result": {"codes": codes} if codes else None,
    }


@app.post("/api/docx/cancel/{job_id}")
def docx_cancel(job_id: str):
    """Cancela extração DOCX em andamento — sem API key (job_id é auth suficiente)."""
    ok = cancel_job(job_id)
    if not ok:
        return {"error": "Job não encontrado"}
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/api/extractor/status/{job_id}")
def extractor_job_status(job_id: str):
    """Polling de status do job PPTX Extractor — sem API key."""
    job = get_job(job_id)
    if not job:
        return {"status": "not_found", "logs": [], "error": "Job não encontrado"}
    result = job.result or {}
    return {
        "status": job.status,
        "logs": job.logs,
        "error": job.error,
        "total": len(result.get("questoes", [])),
        "comentario": result.get("comentario"),   # preenchido apenas no gerar-comentario
    }


@app.get("/api/extractor/download/{job_id}")
def extractor_download(job_id: str):
    """Download do .xlsx de questões — sem API key (job_id UUID é auth suficiente)."""
    import io
    from fastapi.responses import StreamingResponse
    from services.pptx_extractor_service import questoes_to_xlsx_bytes
    job = get_job(job_id)
    if not job or not job.result:
        return {"error": "Job não encontrado ou sem resultado"}
    questoes = job.result.get("questoes", [])
    xlsx_bytes = questoes_to_xlsx_bytes(questoes)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=questoes_pptx_{job_id[:8]}.xlsx"},
    )


@app.post("/api/pdf/cancel/{job_id}")
def pdf_cancel(job_id: str):
    """Cancela extração PDF em andamento — sem API key (job_id é auth suficiente)."""
    ok = cancel_job(job_id)
    if not ok:
        return {"error": "Job não encontrado"}
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/health")
def health():
    """Diagnóstico mínimo — apenas confirma se a chave está configurada."""
    return {
        "api_secret_key_set": bool(os.environ.get("API_SECRET_KEY", "")),
        "cors_configured": bool(_raw_origins),
    }
