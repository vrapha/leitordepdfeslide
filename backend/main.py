"""
EMR Web App — FastAPI Backend
Dois módulos: Leitor de Slides (PPTX) e Leitor de PDF (extração de códigos).
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import slides, pdf, auth

# Em produção, defina ALLOWED_ORIGIN no Railway com o domínio do Lovable.
# Ex: https://meu-app.lovable.app
# Separe múltiplos com vírgula: https://app1.lovable.app,https://app2.lovable.app
_raw_origins = os.environ.get("ALLOWED_ORIGIN", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

# Em produção (API_SECRET_KEY definida), nunca permitir wildcard
if _is_production and "*" in ALLOWED_ORIGINS:
    import sys
    print(
        "ERRO: ALLOWED_ORIGIN não está configurado. "
        "Defina a variável no Railway com o domínio do Lovable. "
        "Ex: https://meu-app.lovable.app",
        file=sys.stderr,
    )
    # Bloqueia totalmente até que seja configurado corretamente
    ALLOWED_ORIGINS = []

# Oculta /docs e /redoc em produção (quando API_SECRET_KEY está definida)
_is_production = bool(os.environ.get("API_SECRET_KEY", ""))
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
