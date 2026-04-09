# EMR Web App — Leitor de Slides + Leitor de PDF

Aplicação web com dois módulos:
1. **Leitor de Slides** — Analisa PPTX com questões médicas, detecta gabaritos via marcador vermelho e gera comentários detalhados via ChatGPT
2. **Leitor de PDF** — Extrai questões de PDFs acadêmicos e encontra os códigos correspondentes no painel `manager.eumedicoresidente.com.br`

## Arquitetura

```
Frontend (React + TypeScript) → Lovable
Backend (FastAPI + Playwright) → Railway
```

## Como rodar localmente

### Backend

```bash
cd backend
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Acesse: http://localhost:5173

## Deploy

### Backend → Railway
1. Crie conta em railway.app
2. Novo projeto → Deploy from GitHub
3. Selecione a pasta `backend/`
4. Railway detecta o `Dockerfile` automaticamente

### Frontend → Lovable
1. Importe o projeto no Lovable
2. Configure `VITE_API_URL` com a URL do Railway
3. Deploy!

## Fluxo de uso

### Leitor de Slides
1. Carregue o `.pptx`
2. (Opcional) Cole o gabarito manual
3. Clique **Analisar Slides** — detecta respostas automaticamente
4. Edite respostas com duplo clique na tabela
5. Faça login no ChatGPT (botão Login)
6. Clique **Iniciar Automação** — bot gera comentários
7. Baixe o PPTX processado

### Leitor de PDF
1. Faça login no painel (botão Login Painel)
2. Carregue o `.pdf`
3. Defina a meta de códigos
4. Clique **Extrair Questões**
5. Baixe o CSV com os códigos

## Estrutura de arquivos

```
leitordepdfeslide/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── routers/
│   │   ├── slides.py        # Endpoints PPTX
│   │   ├── pdf.py           # Endpoints PDF
│   │   └── auth.py          # Gestão de sessões
│   ├── services/
│   │   ├── job_manager.py   # Jobs + WebSocket
│   │   ├── ppt_service.py   # Orquestração parsers
│   │   ├── chatbot_service.py # Bot ChatGPT
│   │   └── pdf_service.py   # Extração PDF + scraping
│   └── parsers/
│       ├── ppt_parser.py        # Parser padrão
│       ├── ppt_robust_parser.py # Parser XML (primário)
│       └── ppt_xml_parser.py    # Parser fallback
└── frontend/
    └── src/
        ├── pages/
        │   ├── SlidesPage.tsx
        │   └── PDFPage.tsx
        ├── components/
        │   ├── Layout.tsx
        │   ├── FileUpload.tsx
        │   ├── ResultsTable.tsx
        │   └── LogViewer.tsx
        └── api/client.ts
```
