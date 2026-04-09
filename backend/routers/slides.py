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

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from services.job_manager import create_job, get_job, make_logger
from services.ppt_service import analyze_ppt, build_prompt, save_response_to_notes
from services.chatbot_service import ChatGPTBot
from parsers.ppt_parser import PPTParser

router = APIRouter()
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
    pptx_path = UPLOADS_DIR / f"{job.id}_{file.filename}"
    content = await file.read()
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
            job.result = {"slides": clean, "pptx_path": str(pptx_path), "job_id": job.id}
            job.status = "done"
        except Exception as e:
            logger(f"Erro: {e}", "ERROR")
            job.status = "error"
            job.error = str(e)

    await loop.run_in_executor(None, run)

    if job.status == "error":
        return {"error": job.error, "job_id": job.id}

    return job.result


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
    pptx_path = source_job.result["pptx_path"] if source_job and source_job.result else ""

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
    """Roda em background thread (Playwright é síncrono)."""
    job = get_job(job_id)
    if not job:
        return

    logger = make_logger(job)
    job.status = "running"

    valid = [s for s in slides_data if s.get("correct_answer")]
    logger(f"Iniciando processamento de {len(valid)} questões.")

    if not valid:
        logger("Nenhuma resposta detectada. Abortando.")
        job.status = "done"
        return

    output_file = pptx_path.replace(".pptx", "_Analyzed.pptx")

    bot = ChatGPTBot(headless=False, logger=logger)
    try:
        bot.start()
        logger("Aguardando login no ChatGPT...")
        bot.ensure_login()
    except Exception as e:
        logger(f"Falha no login: {e}", "ERROR")
        bot.close()
        job.status = "error"
        job.error = str(e)
        return

    try:
        parser = PPTParser(pptx_path)
    except Exception as e:
        logger(f"Erro ao reabrir PPTX: {e}", "ERROR")
        bot.close()
        job.status = "error"
        job.error = str(e)
        return

    processed = 0
    RESET_INTERVAL = 25

    for item in slides_data:
        q_num = item.get("question_number", 0)
        correct = item.get("correct_answer")

        try:
            if int(q_num) < start_question:
                continue
        except Exception:
            pass

        if not correct or correct == "None":
            logger(f"Pulando Q{q_num} — sem resposta")
            continue

        if processed > 0 and processed % RESET_INTERVAL == 0:
            logger(f"Resetando conversa após {processed} questões...")
            bot.new_conversation()

        logger(f"Processando Q{q_num} (Slide {item['slide_index'] + 1}) — Resposta: {correct}")

        prompt = build_prompt(
            item.get("question", ""),
            item.get("alternatives", []),
            correct,
        )

        response = bot.query(prompt)

        if response.startswith("Error:"):
            logger(f"Erro na Q{q_num}: {response}. Tentando novamente...")
            bot.new_conversation()
            response = bot.query(prompt)
            if response.startswith("Error:"):
                logger(f"Q{q_num} falhou após retry. Pulando.")
                continue

        try:
            save_response_to_notes(parser, item["slide_index"], response, output_file)
            logger(f"Slide {item['slide_index'] + 1} salvo em {Path(output_file).name}")
        except Exception as e:
            logger(f"Erro ao salvar slide {item['slide_index'] + 1}: {e}", "ERROR")

        processed += 1

    bot.close()
    job.result = {"output_file": output_file, "processed": processed}
    job.status = "done"
    logger(f"Concluído! {processed} questões processadas. Arquivo: {Path(output_file).name}")


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
    """Transmite logs do job em tempo real via WebSocket."""
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
