"""
EMR Web App — FastAPI Backend
Dois módulos: Leitor de Slides (PPTX) e Leitor de PDF (extração de códigos).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import slides, pdf, auth

app = FastAPI(
    title="EMR Web App",
    description="Leitor de Slides PPTX + Leitor de PDF com automação Playwright",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, substitua pelo domínio do Lovable
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(slides.router, prefix="/api/slides", tags=["slides"])
app.include_router(pdf.router, prefix="/api/pdf", tags=["pdf"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])


@app.get("/")
def root():
    return {"status": "ok", "message": "EMR Web App Backend"}
