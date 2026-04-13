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

Premissas do Word (diferente do PDF):
  - TODAS as questões estão garantidamente no Manager → busca agressiva, sem desistência
  - Quantidade de questões é variável → detectada automaticamente no arquivo
  - Resultado retornado em ordem (Q1, Q2, Q3...) com código ou "NÃO ENCONTRADO"
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from docx import Document as DocxDocument

# Reutiliza toda a lógica de busca do PDF service
from services.pdf_service import (
    QuestionBlock,
    STORAGE_STATE,
    _ensure_logged_in_and_save_state,
    build_queries_from_enunciado,
    goto_filter_page,
    wait_results,
    parse_listagem_texto,
    validate_question_match,
    SiteQuestion,
    MatchResult,
    count_pdf_alternatives,
    MAX_QUERY_CHARS,
)
from rapidfuzz import fuzz
from unidecode import unidecode

# ─── Parâmetros agressivos para Word ────────────────────────────────────────
# Como TODAS as questões estão no Manager, nunca desistimos cedo
DOCX_MAX_QUERIES   = 120   # mais tentativas que o PDF (era 80)
DOCX_SMART_STOP    = 9999  # desativa smart-stop — nunca abandona
DOCX_MIN_SCORE     = 0     # sem score mínimo para continuar tentando
DOCX_MAX_PAGES     = 8     # páginas por query
DOCX_SPECIALTY_IDX = 3
# ────────────────────────────────────────────────────────────────────────────


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


def _parse_alternative(text: str):
    """Retorna (letra, texto) se for alternativa, senão (None, None)."""
    m = re.match(r"^([A-E])[\.\)]\s+(.+)", text.strip())
    if m:
        return m.group(1), _compact(m.group(2))
    return None, None


def parse_questoes_from_docx(
    docx_path: str,
    logger: Callable = print,
) -> List[QuestionBlock]:
    """
    Lê um .docx e retorna lista de QuestionBlock em ordem.
    Detecta automaticamente quantas questões existem no arquivo.
    """
    doc = DocxDocument(docx_path)
    paragraphs = [_compact(p.text) for p in doc.paragraphs]

    # Localiza início da PARTE 2 (ou fallback: primeira "Questão 1")
    parte2_idx = None
    for i, text in enumerate(paragraphs):
        if re.search(r"PARTE\s+2", text, re.I):
            parte2_idx = i
            break

    if parte2_idx is None:
        for i, text in enumerate(paragraphs):
            if _is_questao_header(text) == 1:
                parte2_idx = i
                break

    if parte2_idx is None:
        raise RuntimeError(
            "Não foi possível localizar a seção de questões. "
            "Verifique se o arquivo contém 'PARTE 2' ou 'Questão 1'."
        )

    logger(f"Seção de questões localizada. Detectando questões automaticamente...")

    # Parsing
    questions: List[QuestionBlock] = []
    current_numero: Optional[int] = None
    current_enunciado_parts: List[str] = []
    current_alternativas: Dict[str, str] = {}
    in_enunciado = False

    def flush():
        nonlocal current_numero, current_enunciado_parts, current_alternativas, in_enunciado
        if current_numero is None:
            return
        enunciado = _compact(" ".join(current_enunciado_parts))
        alts = dict(current_alternativas)
        if len(enunciado.split()) >= 3:
            questions.append(QuestionBlock(
                numero=current_numero,
                tipo="ACESSO_DIRETO",
                enunciado=enunciado,
                alternativas=alts,
                texto_completo=enunciado,
            ))
        current_numero = None
        current_enunciado_parts = []
        current_alternativas = {}
        in_enunciado = False

    for text in paragraphs[parte2_idx + 1:]:
        if not text:
            continue

        num = _is_questao_header(text)
        if num is not None:
            flush()
            current_numero = num
            in_enunciado = False
            continue

        if current_numero is None:
            continue

        if _is_banca_line(text):
            in_enunciado = True
            continue

        letra, alt_text = _parse_alternative(text)
        if letra:
            in_enunciado = False
            if alt_text:
                current_alternativas[letra] = alt_text
            continue

        if in_enunciado:
            current_enunciado_parts.append(text)

    flush()

    logger(f"{len(questions)} questões detectadas no documento.")
    return questions


# ─────────── Busca agressiva para Word ───────────

def _find_code_docx(
    page,
    questao: QuestionBlock,
    logger: Callable = print,
) -> Optional[MatchResult]:
    """
    Versão agressiva de find_code_for_question para Word.
    Nunca desiste — todas as questões estão garantidamente no Manager.
    """
    from urllib.parse import quote_plus
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    queries = build_queries_from_enunciado(questao.enunciado, questao.alternativas)
    total_pdf = count_pdf_alternatives(questao.alternativas) or 4
    seen_codes: set[str] = set()
    best_media: Optional[tuple] = None
    best_baixa: Optional[tuple] = None
    query_count = 0
    max_score_seen = 0

    logger(f"  [{questao.numero}] {len(queries)} queries geradas.")

    for q in queries[:DOCX_MAX_QUERIES]:
        query_count += 1
        per_page = 25

        for pnum in range(1, DOCX_MAX_PAGES + 1):
            goto_filter_page(page, q, pnum)
            wait_results(page)

            rows = page.evaluate(
                f"""() => {{
                    const out = [];
                    for (const tr of document.querySelectorAll('table tbody tr')) {{
                        const tds = tr.querySelectorAll('td');
                        if (!tds || tds.length < {DOCX_SPECIALTY_IDX + 1}) continue;
                        const code = (tds[1]?.innerText || '').trim();
                        const desc = (tds[2]?.innerText || '').trim();
                        const esp  = (tds[{DOCX_SPECIALTY_IDX}]?.innerText || '').trim();
                        if (code && desc) out.push({{code, desc, esp}});
                    }}
                    return out;
                }}"""
            )

            if not rows:
                break

            for r in rows[:per_page]:
                code = (r.get("code") or "").strip()
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                raw_desc = (r.get("desc") or "").strip()
                esp = (r.get("esp") or "").strip()
                if not raw_desc:
                    continue

                enun, alts, is_ad = parse_listagem_texto(raw_desc)
                if not enun:
                    continue

                sq = SiteQuestion(code, enun, alts, is_ad, esp)
                match_ok, score, num_alt = validate_question_match(questao, sq)
                max_score_seen = max(max_score_seen, score)

                if not match_ok:
                    continue

                ratio = num_alt / total_pdf if total_pdf else 0
                if score >= 90 and ratio >= 0.75:
                    confianca = "ALTA"
                elif score >= 80 and ratio >= 0.60:
                    confianca = "MEDIA"
                else:
                    confianca = "BAIXA"

                result = MatchResult(code, score, num_alt, confianca, is_ad, esp)
                rank = score * 10 + num_alt

                if confianca == "ALTA":
                    return result
                if confianca == "MEDIA":
                    if best_media is None or rank > best_media[1]:
                        best_media = (result, rank)
                else:
                    if best_baixa is None or rank > best_baixa[1]:
                        best_baixa = (result, rank)

            # Retorno antecipado se score muito bom
            if best_media and best_media[0].score_enunciado >= 90:
                return best_media[0]

    # Retorna o melhor encontrado mesmo se confiança baixa
    result = (best_media[0] if best_media else None) or (best_baixa[0] if best_baixa else None)
    if not result:
        logger(f"  [{questao.numero}] Não encontrado após {query_count} queries. Melhor score: {max_score_seen}%")
    return result


# ─────────── Extração principal ───────────

def run_docx_extraction(
    docx_path: str,
    logger: Callable = print,
) -> List[str]:
    """
    Extrai códigos de TODAS as questões do .docx em ordem (Q1, Q2, Q3...).
    Retorna lista com código ou marcador de não encontrado para cada questão.
    """
    from playwright.sync_api import sync_playwright

    if not Path(docx_path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {docx_path}")

    logger("=" * 50)
    logger("EXTRAÇÃO DE QUESTÕES DO WORD")
    logger("=" * 50)

    questions = parse_questoes_from_docx(docx_path, logger)
    total = len(questions)

    if not questions:
        raise RuntimeError("Nenhuma questão foi encontrada no documento.")

    logger(f"Total de questões a processar: {total}")

    if not Path(STORAGE_STATE).exists():
        raise RuntimeError(
            "Sessão do painel não encontrada. "
            "Use o botão 'Login Painel' para autenticar primeiro."
        )

    # Resultado em ordem: índice = número da questão - 1
    results: List[str] = []
    found_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=30)
        context = browser.new_context(storage_state=STORAGE_STATE)
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        _ensure_logged_in_and_save_state(page, context, STORAGE_STATE)

        for idx, questao in enumerate(questions, 1):
            numero = questao.numero or idx
            preview = (questao.enunciado[:100] + "...") if len(questao.enunciado) > 100 else questao.enunciado
            logger(f"[{idx}/{total}] Q{numero}: {preview}")

            match = _find_code_docx(page, questao, logger)

            if match:
                codigo = f"{match.code}"
                results.append(codigo)
                found_count += 1
                logger(f"  ✓ ENCONTRADO: {codigo} (score={match.score_enunciado}%, {match.confianca}) [{found_count}/{total}]")
            else:
                results.append(f"Q{numero}_NAO_ENCONTRADO")
                logger(f"  ✗ NÃO ENCONTRADO [{found_count}/{total}]")

        browser.close()

    logger(f"CONCLUÍDO: {found_count}/{total} códigos encontrados.")
    return results
