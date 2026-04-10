"""
Router: /api/auth
Gerencia sessões salvas para ChatGPT e painel web.
- GET  /chatgpt/status        — verifica se auth.json existe
- POST /chatgpt/login         — abre browser para login manual (background)
- POST /chatgpt/upload        — faz upload do auth.json gerado localmente
- GET  /site/status           — verifica se storage_state.json existe
- POST /site/login            — abre browser para login manual no painel
- POST /site/upload           — faz upload do storage_state.json gerado localmente
"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile

from services.job_manager import create_job, get_job, make_logger
from security import require_api_key, validate_json_file

router = APIRouter(dependencies=[Depends(require_api_key)])

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
CHATGPT_AUTH = SESSIONS_DIR / "auth.json"
SITE_AUTH = SESSIONS_DIR / "storage_state.json"


@router.get("/chatgpt/status")
def chatgpt_status():
    return {"has_session": CHATGPT_AUTH.exists()}


@router.post("/chatgpt/login")
def chatgpt_login(background_tasks: BackgroundTasks):
    """Abre o Chrome para login manual no ChatGPT."""
    job = create_job()
    background_tasks.add_task(_run_chatgpt_login, job.id)
    return {"job_id": job.id, "message": "Browser aberto. Faça login e aguarde a confirmação."}


def _run_chatgpt_login(job_id: str):
    from services.chatbot_service import ChatGPTBot
    job = get_job(job_id)
    if not job:
        return
    logger = make_logger(job)
    job.status = "running"
    bot = ChatGPTBot(headless=False, logger=logger)
    try:
        bot.start()
        logger("Faça login no ChatGPT no navegador que abriu.")
        bot.ensure_login(timeout_seconds=300)
        logger("Login realizado e sessão salva!")
        job.result = {"success": True}
        job.status = "done"
    except Exception as e:
        logger(f"Erro no login: {e}", "ERROR")
        job.status = "error"
        job.error = str(e)
    finally:
        bot.close()


@router.get("/site/status")
def site_status():
    return {"has_session": SITE_AUTH.exists()}


@router.post("/site/login")
def site_login(background_tasks: BackgroundTasks):
    """Abre o Chrome para login manual no painel web."""
    job = create_job()
    background_tasks.add_task(_run_site_login, job.id)
    return {"job_id": job.id, "message": "Browser aberto. Faça login no painel e aguarde."}


def _run_site_login(job_id: str):
    from playwright.sync_api import sync_playwright
    job = get_job(job_id)
    if not job:
        return
    logger = make_logger(job)
    job.status = "running"
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            logger("Abrindo painel web...")
            page.goto(
                "https://manager.eumedicoresidente.com.br/admin/resources/Question",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            url = page.url.lower()
            if "/login" not in url:
                context.storage_state(path=str(SITE_AUTH))
                logger("Sessão já válida! Salva com sucesso.")
                job.result = {"success": True}
                job.status = "done"
                browser.close()
                return

            logger("Faça login no painel manualmente. Aguardando...")
            import time
            for _ in range(600):
                time.sleep(1)
                url = (page.url or "").lower()
                on_admin = "/admin/resources" in url or url.endswith("/admin")
                if on_admin:
                    context.storage_state(path=str(SITE_AUTH))
                    logger("Login detectado! Sessão salva.")
                    job.result = {"success": True}
                    job.status = "done"
                    break
            else:
                raise TimeoutError("Timeout aguardando login no painel.")

            browser.close()
    except Exception as e:
        logger(f"Erro no login: {e}", "ERROR")
        job.status = "error"
        job.error = str(e)


@router.post("/chatgpt/upload")
async def upload_chatgpt_session(file: UploadFile = File(...)):
    """
    Recebe o auth.json gerado localmente e salva no servidor.
    Requer autenticação via X-API-Key (aplicada no router).
    """
    content = await validate_json_file(file)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    CHATGPT_AUTH.write_bytes(content)
    return {"success": True, "message": "auth.json salvo com sucesso no servidor."}


@router.post("/site/upload")
async def upload_site_session(file: UploadFile = File(...)):
    """
    Recebe o storage_state.json gerado localmente e salva no servidor.
    Requer autenticação via X-API-Key (aplicada no router).
    """
    content = await validate_json_file(file)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    SITE_AUTH.write_bytes(content)
    return {"success": True, "message": "storage_state.json salvo com sucesso no servidor."}


@router.get("/login/status/{job_id}")
def login_status(job_id: str):
    """Verifica o status de um job de login."""
    job = get_job(job_id)
    if not job:
        return {"error": "Job não encontrado"}
    return {
        "job_id": job_id,
        "status": job.status,
        "logs": job.logs[-20:],
        "error": job.error,
    }
