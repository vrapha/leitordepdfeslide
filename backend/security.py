"""
Segurança centralizada da aplicação.
- API Key obrigatória em todas as rotas via header X-API-Key
- Validação de tipo e tamanho de arquivo
"""
import os
from fastapi import HTTPException, Security, UploadFile
from fastapi.security.api_key import APIKeyHeader

API_KEY_NAME = "X-API-Key"
_api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Carregado do env var API_SECRET_KEY (configurado no Railway e no Lovable)
_SECRET_KEY: str = os.environ.get("API_SECRET_KEY", "")

MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_TYPES = {
    "pdf": ["application/pdf"],
    "pptx": [
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",  # alguns browsers enviam assim
    ],
    "json": ["application/json", "application/octet-stream"],
}


def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    """Dependência FastAPI — rejeita se API key inválida ou ausente."""
    if not _SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="API_SECRET_KEY não configurada no servidor.",
        )
    if api_key != _SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail="API Key inválida ou ausente. Use o header X-API-Key.",
        )
    return api_key


def validate_file(file: UploadFile, file_type: str) -> None:
    """Valida content-type do arquivo enviado."""
    allowed = ALLOWED_TYPES.get(file_type, [])
    content_type = (file.content_type or "").split(";")[0].strip()
    if allowed and content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de arquivo inválido: {content_type}. Esperado: {file_type.upper()}",
        )


async def validate_file_size(file: UploadFile) -> bytes:
    """Lê o conteúdo e valida o tamanho. Retorna os bytes lidos."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE_MB}MB",
        )
    return content
