"""
Router: /api/pdf
- POST /extract        — upload de PDF → inicia extração em background
- GET  /result/{job_id} — retorna lista de códigos extraídos
- GET  /download/{job_id} — baixa CSV com os códigos
- WS   /ws/{job_id}    — stream de logs em tempo real
"""
import asyncio
import csv
import io
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from services.job_manager import create_job, get_job, make_logger, cancel_job
from services.pdf_service import run_pdf_extraction
from security import require_api_key, check_websocket_key, validate_pdf

router = APIRouter(dependencies=[Depends(require_api_key)])
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/extract")
async def extract_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target: int = Form(30),
):
    """
    Inicia extração de códigos do PDF em background.
    target = número máximo de códigos a encontrar.
    """
    content = await validate_pdf(file)

    job = create_job()
    safe_name = Path(file.filename or "upload.pdf").name
    pdf_path = UPLOADS_DIR / f"{job.id}_{safe_name}"
    pdf_path.write_bytes(content)

    background_tasks.add_task(_run_extraction_thread, job.id, str(pdf_path), target)

    return {"job_id": job.id, "status": "running"}


def _run_extraction_thread(job_id: str, pdf_path: str, target: int):
    """Roda a extração em thread síncrona (Playwright)."""
    job = get_job(job_id)
    if not job:
        return

    logger = make_logger(job)
    job.status = "running"

    try:
        codes = run_pdf_extraction(
            pdf_path=pdf_path,
            logger=logger,
            headless=True,
            target_encontradas=target,
            job_id=job_id,
        )
        job.result = {"codes": codes}
        if not job.cancelled:
            job.status = "done"
    except Exception as e:
        logger(f"Erro: {e}", "ERROR")
        job.status = "error"
        job.error = str(e)


@router.post("/cancel/{job_id}")
async def cancel_pdf(job_id: str):
    """Cancela uma extração em andamento. Salva resultado parcial."""
    ok = cancel_job(job_id)
    if not ok:
        return {"error": "Job não encontrado"}
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Polling endpoint: retorna status, logs acumulados e resultado."""
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


@router.get("/result/{job_id}")
async def get_result(job_id: str):
    """Retorna os códigos extraídos."""
    job = get_job(job_id)
    if not job:
        return {"error": "Job não encontrado"}
    return {
        "job_id": job_id,
        "status": job.status,
        "codes": job.result.get("codes", []) if job.result else [],
        "error": job.error,
    }


@router.get("/download/{job_id}")
async def download_csv(job_id: str):
    """Baixa os códigos como CSV."""
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
        headers={"Content-Disposition": f"attachment; filename=codigos_{job_id[:8]}.csv"},
    )


@router.websocket("/ws/{job_id}")
async def websocket_logs(websocket: WebSocket, job_id: str, api_key: str = ""):
    """Transmite logs do job em tempo real. Autenticação via query param api_key."""
    if not check_websocket_key(api_key):
        await websocket.close(code=4001)
        return
    await websocket.accept()
    job = get_job(job_id)
    if not job:
        await websocket.send_text("[ERROR] Job não encontrado")
        await websocket.close()
        return

    for log in job.logs:
        await websocket.send_text(log)

    try:
        while job.status in ("pending", "running"):
            try:
                msg = await asyncio.wait_for(job.log_queue.get(), timeout=1.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                continue
        while not job.log_queue.empty():
            msg = job.log_queue.get_nowait()
            await websocket.send_text(msg)
        await websocket.send_text(f"__STATUS__{job.status}")
    except WebSocketDisconnect:
        pass
