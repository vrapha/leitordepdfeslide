"""
Segurança centralizada da aplicação.
- API Key obrigatória em todas as rotas via header X-API-Key
- Validação de tipo e tamanho por magic bytes (não apenas Content-Type)
"""
import io
import os
import zipfile
from pathlib import Path

from fastapi import HTTPException, Security, UploadFile
from fastapi.security.api_key import APIKeyHeader

API_KEY_NAME = "X-API-Key"
_api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def _get_secret() -> str:
    """Lê API_SECRET_KEY do ambiente a cada chamada (nunca em cache)."""
    return os.environ.get("API_SECRET_KEY", "")


def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    """Dependência FastAPI — rejeita se API key inválida ou ausente."""
    secret = _get_secret()
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="API_SECRET_KEY não configurada no servidor.",
        )
    if api_key != secret:
        raise HTTPException(
            status_code=401,
            detail="API Key inválida ou ausente.",
        )
    return api_key


def check_websocket_key(api_key: str) -> bool:
    """Verifica API key para WebSocket (retorna bool em vez de raise)."""
    secret = _get_secret()
    if not secret:
        return False
    return api_key == secret


async def validate_pdf(file: UploadFile) -> bytes:
    """Valida e lê arquivo PDF — verifica magic bytes e tamanho."""
    content = await file.read()

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE_MB}MB",
        )
    # Magic bytes do PDF: %PDF
    if not content.startswith(b"%PDF"):
        raise HTTPException(
            status_code=400,
            detail="Arquivo inválido. Envie um PDF real.",
        )
    return content


async def validate_pptx(file: UploadFile) -> bytes:
    """Valida e lê arquivo PPTX — verifica magic bytes ZIP e estrutura interna."""
    content = await file.read()

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE_MB}MB",
        )
    # PPTX é um ZIP — magic bytes: PK\x03\x04
    if not content.startswith(b"PK\x03\x04"):
        raise HTTPException(
            status_code=400,
            detail="Arquivo inválido. Envie um PPTX real.",
        )
    # Verifica estrutura interna do PPTX
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            if not any(n.startswith("ppt/slides/") for n in names):
                raise HTTPException(
                    status_code=400,
                    detail="Arquivo PPTX não contém slides válidos.",
                )
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=400,
            detail="Arquivo PPTX corrompido.",
        )
    return content


async def validate_json_file(file: UploadFile) -> bytes:
    """Valida e lê arquivo JSON para upload de sessão."""
    import json

    content = await file.read()

    if len(content) > 5 * 1024 * 1024:  # 5MB max para JSON de sessão
        raise HTTPException(
            status_code=413,
            detail="Arquivo de sessão muito grande.",
        )
    try:
        json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Arquivo inválido. Envie um JSON válido.",
        )
    return content


def safe_output_path(source_path: str, suffix: str, uploads_dir: Path) -> Path:
    """Gera caminho de saída seguro, garantindo que fique dentro de uploads_dir."""
    src = Path(source_path).resolve()
    out = src.parent / f"{src.stem}{suffix}"
    # Garantia: arquivo de saída deve estar dentro do uploads_dir
    try:
        out.relative_to(uploads_dir.resolve())
    except ValueError:
        raise ValueError(
            f"Tentativa de path traversal detectada: {out}"
        )
    return out
