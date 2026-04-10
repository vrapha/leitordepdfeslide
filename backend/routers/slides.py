"""
Router: /api/slides
- POST /analyze   — upload de PPTX + gabarito → retorna slides_data
- POST /process   — inicia bot ChatGPT em background
- GET  /download/{job_id} — baixa PPTX processado
- WS   /ws/{job_id}       — stream de logs em tempo real
"""
import asyncio
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from services.job_manager import create_job, get_job, make_logger
from services.ppt_service import analyze_ppt, build_prompt, save_response_to_notes
from services.openai_service import query_openai
from parsers.ppt_parser import PPTParser
from security import require_api_key, check_websocket_key, validate_pptx, safe_output_path

router = APIRouter(dependencies=[Depends(require_api_key)])
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/analyze")
async def analyze_slides(
    file: UploadFile = File(...),
    gabarito: str = Form(""),
):
    """Analisa o PPTX e retorna os dados de cada slide."""
    job = create_job()
    logger = make_logger(job)

    # Salva o arquivo enviado
    content = await validate_pptx(file)
    safe_name = Path(file.filename or "upload.pptx").name
    pptx_path = UPLOADS_DIR / f"{job.id}_{safe_name}"
    pptx_path.write_bytes(content)

    # Roda análise de forma síncrona (rápido o suficiente)
    loop = asyncio.get_event_loop()

    def run():
        job.status = "running"
        try:
            slides = analyze_ppt(str(pptx_path), gabarito or None, logger)
            # Remove o objeto slide_obj não serializável
            clean = []
            for item in slides:
                clean.append({
                    "slide_index": item["slide_index"],
                    "question_number": item.get("question_number"),
                    "question": item.get("question", ""),
                    "alternatives": item.get("alternatives", []),
                    "correct_answer": item.get("correct_answer"),
                })
            # pptx_path armazenado internamente no job, não exposto na resposta
            job.result = {"slides": clean, "pptx_path": str(pptx_path), "job_id": job.id}
            job.status = "done"
        except Exception as e:
            logger("Erro ao processar arquivo.", "ERROR")
            job.status = "error"
            job.error = "Erro ao processar arquivo."

    await loop.run_in_executor(None, run)

    if job.status == "error":
        return {"error": job.error, "job_id": job.id}

    # Nunca expor pptx_path na resposta — apenas slides e job_id
    result = job.result or {}
    return {"job_id": result.get("job_id"), "slides": result.get("slides", [])}


@router.post("/process")
async def process_slides(
    background_tasks: BackgroundTasks,
    job_data: dict[str, Any],
):
    """
    Inicia processamento com ChatGPT em background.
    Body: {job_id, slides_data, start_question}
    """
    source_job_id: str = job_data.get("job_id", "")
    slides_data: list[dict] = job_data.get("slides_data", [])
    start_question: int = int(job_data.get("start_question", 0))

    source_job = get_job(source_job_id)
    if not source_job or not source_job.result:
        return {"error": "Job de análise não encontrado. Reenvie o arquivo."}

    pptx_path = source_job.result.get("pptx_path", "")
    if not pptx_path or not Path(pptx_path).exists():
        return {"error": "Arquivo PPTX original não encontrado no servidor."}

    process_job = create_job()
    background_tasks.add_task(
        _run_processing_thread, process_job.id, pptx_path, slides_data, start_question
    )
    return {"process_job_id": process_job.id}


def _run_processing_thread(
    job_id: str,
    pptx_path: str,
    slides_data: list[dict],
    start_question: int,
):
    """Processa questões via OpenAI API em background thread."""
    job = get_job(job_id)
    if not job:
        return

    logger = make_logger(job)
    job.status = "running"

    valid = [s for s in slides_data if s.get("correct_answer")]
    logger(f"Iniciando processamento de {len(valid)} questões via OpenAI.")

    if not valid:
        logger("Nenhuma resposta detectada. Abortando.")
        job.status = "done"
        return

    output_file = str(safe_output_path(pptx_path, "_Analyzed.pptx", UPLOADS_DIR))

    try:
        parser = PPTParser(pptx_path)
    except Exception as e:
        logger("Erro ao abrir arquivo PPTX.", "ERROR")
        job.status = "error"
        job.error = "Erro ao abrir arquivo PPTX."
        return

    processed = 0
    total = sum(
        1 for s in slides_data
        if s.get("correct_answer") and s.get("correct_answer") != "None"
        and _should_process(s.get("question_number", 0), start_question)
    )

    for item in slides_data:
        q_num = item.get("question_number", 0)
        correct = item.get("correct_answer")

        if not _should_process(q_num, start_question):
            continue

        if not correct or correct == "None":
            logger(f"Pulando Q{q_num} — sem resposta.")
            continue

        logger(f"[{processed + 1}/{total}] Processando Q{q_num} — Gabarito: {correct}")

        prompt = build_prompt(
            item.get("question", ""),
            item.get("alternatives", []),
            correct,
        )

        try:
            response = query_openai(prompt, logger)
        except RuntimeError as e:
            logger(str(e), "ERROR")
            job.status = "error"
            job.error = str(e)
            return
        except Exception:
            logger(f"Q{q_num} falhou. Pulando.", "ERROR")
            continue

        try:
            save_response_to_notes(parser, item["slide_index"], response, output_file)
            logger(f"Q{q_num} salva no slide {item['slide_index'] + 1}.")
        except Exception as e:
            logger(f"Erro ao salvar Q{q_num}: {e}", "ERROR")

        processed += 1

    job.result = {"output_file": output_file, "processed": processed}
    job.status = "done"
    logger(f"Concluído! {processed} questões processadas.")


def _should_process(q_num, start_question: int) -> bool:
    try:
        return int(q_num) >= int(start_question)
    except Exception:
        return True


@router.get("/download/{job_id}")
async def download_result(job_id: str):
    """Baixa o PPTX processado."""
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
    )


@router.websocket("/ws/{job_id}")
async def websocket_logs(websocket: WebSocket, job_id: str):
    """Transmite logs do job em tempo real via WebSocket. job_id UUID é autenticação suficiente."""
    await websocket.accept()
    job = get_job(job_id)
    if not job:
        await websocket.send_text('[ERROR] Job não encontrado')
        await websocket.close()
        return

    # Envia logs já existentes
    for log in job.logs:
        await websocket.send_text(log)

    # Continua transmitindo novos logs
    try:
        while job.status in ("pending", "running"):
            try:
                msg = await asyncio.wait_for(job.log_queue.get(), timeout=1.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                continue
        # Drena a fila final
        while not job.log_queue.empty():
            msg = job.log_queue.get_nowait()
            await websocket.send_text(msg)
        await websocket.send_text(f"__STATUS__{job.status}")
    except WebSocketDisconnect:
        pass
