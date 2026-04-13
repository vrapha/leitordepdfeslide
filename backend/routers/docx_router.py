"""
Router: /api/docx
- POST /extract        — upload de .docx → inicia extração em background
- GET  /result/{job_id} — retorna lista de códigos extraídos
- GET  /download/{job_id} — baixa CSV com os códigos
"""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from services.job_manager import create_job, get_job, make_logger
from services.docx_service import run_docx_extraction
from security import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/extract")
async def extract_docx(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Inicia extração de códigos do .docx em background. Processa TODAS as questões."""
    content = await file.read()
    if len(content) == 0:
        return {"error": "Arquivo vazio."}

    filename = file.filename or "upload.docx"
    if not filename.lower().endswith(".docx"):
        return {"error": "Apenas arquivos .docx são aceitos."}

    job = create_job()
    safe_name = Path(filename).name
    docx_path = UPLOADS_DIR / f"{job.id}_{safe_name}"
    docx_path.write_bytes(content)

    background_tasks.add_task(_run_extraction_thread, job.id, str(docx_path))

    return {"job_id": job.id, "status": "running"}


def _run_extraction_thread(job_id: str, docx_path: str):
    job = get_job(job_id)
    if not job:
        return

    logger = make_logger(job)
    job.status = "running"

    try:
        codes = run_docx_extraction(
            docx_path=docx_path,
            logger=logger,
        )
        job.result = {"codes": codes}
        job.status = "done"
    except Exception as e:
        logger(f"Erro: {e}", "ERROR")
        job.status = "error"
        job.error = str(e)


@router.get("/result/{job_id}")
async def get_result(job_id: str):
    job = get_job(job_id)
    if not job:
        return {"error": "Job não encontrado"}
    result = job.result or {}
    return {
        "job_id": job_id,
        "status": job.status,
        "codes": result.get("codes", []),
        "principais": result.get("principais", []),
        "reservas": result.get("reservas", []),
        "error": job.error,
    }


@router.get("/download/{job_id}")
async def download_csv(job_id: str):
    job = get_job(job_id)
    if not job or not job.result:
        return {"error": "Job não encontrado ou sem resultado"}

    codes = job.result.get("codes", [])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["codigo"])
    for code in codes:
        writer.writerow([code])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=codigos_word_{job_id[:8]}.csv"},
    )
