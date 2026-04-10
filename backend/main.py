"""
EMR Web App — FastAPI Backend
Dois módulos: Leitor de Slides (PPTX) e Leitor de PDF (extração de códigos).
"""
import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import slides, pdf, auth

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
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health():
    """Diagnóstico mínimo — apenas confirma se a chave está configurada."""
    return {
        "api_secret_key_set": bool(os.environ.get("API_SECRET_KEY", "")),
        "cors_configured": bool(_raw_origins),
    }
