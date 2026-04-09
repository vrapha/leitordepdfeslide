#!/bin/bash
# Inicia display virtual (necessário para Playwright no servidor)
Xvfb :99 -screen 0 1280x800x24 -ac &
export DISPLAY=:99

# Aguarda o Xvfb inicializar
sleep 1

# Inicia o servidor FastAPI na porta definida pelo Railway ($PORT) ou 8000
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
