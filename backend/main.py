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
# Ex: https://meu-app.lovable.app
_raw_origins = os.environ.get("ALLOWED_ORIGIN", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

# Em produção com wildcard: bloqueia CORS totalmente até configurar corretamente
if _is_production and "*" in ALLOWED_ORIGINS:
    print(
        "AVISO: ALLOWED_ORIGIN não configurado. "
        "Defina no Railway com o domínio do Lovable (ex: https://meu-app.lovable.app). "
        "CORS bloqueado até que seja configurado.",
        file=sys.stderr,
    )
    ALLOWED_ORIGINS = []

app = FastAPI(
    title="EMR Web App",
    description="Leitor de Slides PPTX + Leitor de PDF com automação Playwright",
    version="1.0.0",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(slides.router, prefix="/api/slides", tags=["slides"])
app.include_router(pdf.router, prefix="/api/pdf", tags=["pdf"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])


@app.get("/")
def root():
    return {"status": "ok", "message": "EMR Web App Backend"}


@app.get("/health")
def health():
    """Diagnóstico — não expõe valores, só presença."""
    key = os.environ.get("API_SECRET_KEY", "")
    return {
        "api_secret_key_set": bool(key),
        "api_secret_key_length": len(key),
        "allowed_origins": ALLOWED_ORIGINS,
    }
