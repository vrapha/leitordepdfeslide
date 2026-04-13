"""
DOCX Service — Extração de códigos de questões de arquivos Word (.docx).
Mesmo objetivo do PDF Service: buscar cada questão no Manager e retornar códigos.
Estrutura esperada do Word:
  PARTE 1 — BLUEPRINT (ignorado)
  PARTE 2 — SIMULADO
    Questão N
    BANCA ANO | Questão X do banco original
    [enunciado — 1 ou mais parágrafos]
    A. alternativa
    B. alternativa
    ...
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from docx import Document as DocxDocument

# Reutiliza toda a lógica de busca do PDF service
from services.pdf_service import (
    QuestionBlock,
    find_code_for_question,
    STORAGE_STATE,
    QUESTIONS_URL,
    _ensure_logged_in_and_save_state,
)

import re as _re


# ─────────── Parsing do Word ───────────

def _compact(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _is_questao_header(text: str) -> Optional[int]:
    """Retorna o número da questão se a linha for 'Questão N', senão None."""
    m = re.match(r"^Quest[aã]o\s+(\d+)\s*$", text.strip(), re.I)
    return int(m.group(1)) if m else None


def _is_banca_line(text: str) -> bool:
    """Linha de metadata como 'PSU-MG 2025 | Questão 14 do banco original'."""
    return bool(re.search(r"banco\s+original", text, re.I))


def _is_alternative(text: str) -> Optional[str]:
    """Retorna a letra se for linha de alternativa (A. texto), senão None."""
    m = re.match(r"^([A-E])[\.\)]\s+(.+)", text.strip())
    return m.group(1) if m else None


def _extract_alternative_letter_text(text: str):
    m = re.match(r"^([A-E])[\.\)]\s+(.+)", text.strip())
    if m:
        return m.group(1), _compact(m.group(2))
    return None, None


def parse_questoes_from_docx(
    docx_path: str,
    logger: Callable = print,
) -> List[QuestionBlock]:
    """
    Lê um .docx e retorna lista de QuestionBlock prontos para busca no Manager.
    Ignora a PARTE 1 (blueprint/tabelas) e processa apenas a PARTE 2 (simulado).
    """
    doc = DocxDocument(docx_path)
    paragraphs = [_compact(p.text) for p in doc.paragraphs]

    # Localiza início da PARTE 2
    parte2_idx = None
    for i, text in enumerate(paragraphs):
        if re.search(r"PARTE\s+2", text, re.I):
            parte2_idx = i
            break

    if parte2_idx is None:
        # Tenta encontrar o primeiro "Questão 1" como fallback
        for i, text in enumerate(paragraphs):
            if _is_questao_header(text) == 1:
                parte2_idx = i
                break

    if parte2_idx is None:
        raise RuntimeError(
            "Não foi possível localizar a seção de questões no documento. "
            "Verifique se o arquivo contém 'PARTE 2' ou 'Questão 1'."
        )

    logger(f"Seção de questões localizada no parágrafo {parte2_idx}.")

    # Parsing das questões
    questions: List[QuestionBlock] = []
    current_numero: Optional[int] = None
    current_enunciado_parts: List[str] = []
    current_alternativas: Dict[str, str] = {}
    in_enunciado = False  # True após a linha de banca, antes das alternativas

    def flush_question():
        nonlocal current_numero, current_enunciado_parts, current_alternativas, in_enunciado
        if current_numero is None:
            return
        enunciado = _compact(" ".join(current_enunciado_parts))
        alts = dict(current_alternativas)
        if len(enunciado.split()) >= 4:
            q = QuestionBlock(
                numero=current_numero,
                tipo="ACESSO_DIRETO",  # Word não distingue tipo — trata como AD
                enunciado=enunciado,
                alternativas=alts,
                texto_completo=enunciado,
            )
            questions.append(q)
        current_numero = None
        current_enunciado_parts = []
        current_alternativas = {}
        in_enunciado = False

    for text in paragraphs[parte2_idx + 1:]:
        if not text:
            continue

        num = _is_questao_header(text)
        if num is not None:
            flush_question()
            current_numero = num
            in_enunciado = False
            continue

        if current_numero is None:
            continue

        if _is_banca_line(text):
            in_enunciado = True  # Próximos parágrafos são enunciado
            continue

        letra = _is_alternative(text)
        if letra:
            in_enunciado = False
            _, alt_text = _extract_alternative_letter_text(text)
            if alt_text:
                current_alternativas[letra] = alt_text
            continue

        if in_enunciado:
            current_enunciado_parts.append(text)

    flush_question()

    logger(f"{len(questions)} questões extraídas do documento Word.")
    return questions


# ─────────── Extração principal ───────────

def run_docx_extraction(
    docx_path: str,
    logger: Callable = print,
    target_encontradas: int = 70,
) -> List[str]:
    """
    Extrai códigos de um .docx e retorna lista de strings (igual ao PDF service).
    """
    from playwright.sync_api import sync_playwright

    if not Path(docx_path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {docx_path}")

    logger("=" * 50)
    logger("EXTRAÇÃO DE QUESTÕES DO WORD")
    logger("=" * 50)

    questions = parse_questoes_from_docx(docx_path, logger)

    if not questions:
        raise RuntimeError("Nenhuma questão foi encontrada no documento.")

    if not Path(STORAGE_STATE).exists():
        raise RuntimeError(
            "Sessão do painel não encontrada. "
            "Use o botão 'Login Painel' para autenticar primeiro."
        )

    results: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=30)
        context = browser.new_context(storage_state=STORAGE_STATE)
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        _ensure_logged_in_and_save_state(page, context, STORAGE_STATE)

        found_count = 0

        for idx, questao in enumerate(questions, 1):
            if found_count >= target_encontradas:
                break

            numero = questao.numero or idx
            preview = (questao.enunciado[:100] + "...") if len(questao.enunciado) > 100 else questao.enunciado
            logger(f"[{idx}/{len(questions)}] Q{numero}: {preview}")

            match = find_code_for_question(page, questao, logger)

            if match:
                codigo = f"{match.code} (Q{numero} WORD)"
                results.append(codigo)
                found_count += 1
                logger(f"  ENCONTRADO: {codigo} ({match.confianca}) [{found_count}/{target_encontradas}]")
            else:
                logger(f"  NÃO ENCONTRADO [{found_count}/{target_encontradas}]")

        browser.close()

    logger(f"CONCLUÍDO: {len(results)} códigos extraídos.")
    return results
