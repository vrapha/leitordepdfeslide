# Usa a imagem oficial do Playwright (Ubuntu 22.04 + Python 3.11 + Chromium já instalado)
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

# Instala LibreOffice (conversão PPTX→PDF) e Xvfb (display virtual)
RUN apt-get update && apt-get install -y \
    libreoffice \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Garante que o Chromium está instalado na versão correta
RUN playwright install chromium

COPY . .

RUN mkdir -p uploads sessions

EXPOSE 8000

COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
