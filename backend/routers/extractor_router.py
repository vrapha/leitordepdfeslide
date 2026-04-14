"""
Router: /api/extractor
- POST /extract        — upload de .pptx + config → extrai questões (sem browser)
- GET  /status/{job_id} — polling de status (público, sem API key)
- GET  /download/{job_id} — baixa CSV com 27 colunas
"""
import csv
import io
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from services.job_manager import create_job, get_job, make_logger
from services.pptx_extractor_service import (
    extrair_questoes_pptx,
    ProfessorBloco,
    COLUNAS,
    parse_range,
)
from security import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/extract")
async def extract_pptx(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    grande_area: str = Form(""),
    professores_json: str = Form("[]"),
    filtro_exportacao: str = Form(""),
):
    """
    Inicia extração das questões do .pptx em background.

    professores_json: JSON array de objetos:
      [{"range_str": "1-20", "nome_comentario": "Ana Beatriz", "nome_video": "Ana Beatriz"}, ...]
      range_str vazio = todas as questões.
    filtro_exportacao: range de questões a exportar, ex. "1-10, 15" (vazio = todas).
    """
    content = await file.read()
    if len(content) == 0:
        return {"error": "Arquivo vazio."}

    filename = file.filename or "upload.pptx"
    if not filename.lower().endswith(".pptx"):
        return {"error": "Apenas arquivos .pptx são aceitos."}

    # Valida/parseia professores
    try:
        prof_raw = json.loads(professores_json) if professores_json else []
    except Exception:
        return {"error": "professores_json inválido (JSON malformado)."}

    blocos: list[ProfessorBloco] = []
    for p in prof_raw:
        range_str = (p.get("range_str") or "").strip()
        blocos.append(ProfessorBloco(
            range_nums=parse_range(range_str) if range_str else None,
            nome_comentario=(p.get("nome_comentario") or "").strip(),
            nome_video=(p.get("nome_video") or "").strip(),
        ))

    job = create_job()
    safe_name = Path(filename).name
    pptx_path = UPLOADS_DIR / f"{job.id}_{safe_name}"
    pptx_path.write_bytes(content)

    background_tasks.add_task(
        _run_extraction_thread,
        job.id,
        str(pptx_path),
        grande_area,
        blocos,
        filtro_exportacao,
    )

    return {"job_id": job.id, "status": "running"}


def _run_extraction_thread(
    job_id: str,
    pptx_path: str,
    grande_area: str,
    blocos: list,
    filtro_exportacao: str,
):
    job = get_job(job_id)
    if not job:
        return

    logger = make_logger(job)
    job.status = "running"

    try:
        questoes = extrair_questoes_pptx(
            pptx_path=pptx_path,
            grande_area=grande_area,
            professores=blocos,
            filtro_exportacao=filtro_exportacao or None,
            logger=logger,
        )
        job.result = {"questoes": questoes}
        job.status = "done"
    except Exception as e:
        logger(f"Erro: {e}", "ERROR")
        job.status = "error"
        job.error = str(e)


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    """Polling de status — retorna progresso e contagem."""
    job = get_job(job_id)
    if not job:
        return {"status": "not_found", "logs": [], "error": "Job não encontrado"}
    questoes = (job.result or {}).get("questoes", [])
    return {
        "status": job.status,
        "logs": job.logs,
        "error": job.error,
        "total": len(questoes),
    }


@router.get("/result/{job_id}")
async def get_result(job_id: str):
    """Retorna todas as questões extraídas (JSON)."""
    job = get_job(job_id)
    if not job:
        return {"error": "Job não encontrado"}
    questoes = (job.result or {}).get("questoes", [])
    return {
        "job_id": job_id,
        "status": job.status,
        "total": len(questoes),
        "questoes": questoes,
        "error": job.error,
    }


@router.get("/download/{job_id}")
async def download_csv(job_id: str):
    """Baixa as questões como CSV com 27 colunas (formato Manager)."""
    job = get_job(job_id)
    if not job or not job.result:
        return {"error": "Job não encontrado ou sem resultado"}

    questoes = job.result.get("questoes", [])
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUNAS, extrasaction="ignore")
    writer.writeheader()
    for q in questoes:
        writer.writerow({col: q.get(col, "") for col in COLUNAS})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=questoes_pptx_{job_id[:8]}.csv"},
    )
