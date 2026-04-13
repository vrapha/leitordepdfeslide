"""
DOCX Service — Extração de códigos de questões de arquivos Word (.docx).

Estrutura esperada do Word:
  PARTE 1 — BLUEPRINT (ignorado)
  PARTE 2 — SIMULADO
    Questão N  (N = número)
    BANCA ANO | Questão X do banco original
    [enunciado]
    A. / B. / C. / D. / E.
  QUESTÕES DE RESERVA
    Questão R1, Questão R2, ... (mesmo formato)

Premissas:
  - TODAS as questões estão no Manager → busca agressiva, sem desistência
  - Quantidade variável → detectada automaticamente
  - Resultado em ordem, separado em principais e reservas
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from docx import Document as DocxDocument

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
)

# ─── Parâmetros agressivos para Word ────────────────────────────────────────
DOCX_MAX_QUERIES   = 120
DOCX_MAX_PAGES     = 8
DOCX_SPECIALTY_IDX = 3
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class DocxQuestion:
    """Questão do Word com indicação se é reserva."""
    block: QuestionBlock
    is_reserva: bool
    label: str   # "Q1", "Q2" ... ou "R1", "R2" ...


# ─────────── Parsing do Word ───────────

def _compact(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _parse_questao_header(text: str) -> Optional[Tuple[int, bool]]:
    """
    Retorna (numero, is_reserva) se for header de questão, senão None.
    Aceita: 'Questão 1', 'Questão R1', 'Questão R10 | PSU-MG 2025 | ...'
    """
    t = text.strip()
    # Reserva: Questão R1, Questão R2... (pode ter texto extra após o número)
    m = re.match(r"^Quest[aã]o\s+[Rr](\d+)(\s*$|\s*[\|,])", t, re.I)
    if m:
        return int(m.group(1)), True
    # Principal: Questão 1, Questão 2... (pode ter texto extra após o número)
    m = re.match(r"^Quest[aã]o\s+(\d+)(\s*$|\s*[\|,])", t, re.I)
    if m:
        return int(m.group(1)), False
    return None


def _is_banca_line(text: str) -> bool:
    return bool(re.search(r"banco\s+original", text, re.I))


def _parse_alternative(text: str) -> Tuple[Optional[str], Optional[str]]:
    m = re.match(r"^([A-E])[\.\)]\s+(.+)", text.strip())
    if m:
        return m.group(1), _compact(m.group(2))
    return None, None


def parse_questoes_from_docx(
    docx_path: str,
    logger: Callable = print,
) -> List[DocxQuestion]:
    """
    Lê .docx e retorna lista de DocxQuestion em ordem (principais primeiro, depois reservas).
    Detecta automaticamente quantas questões existem.
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
        for i, text in enumerate(paragraphs):
            if _parse_questao_header(text) is not None:
                parte2_idx = i
                break
    if parte2_idx is None:
        raise RuntimeError(
            "Não foi possível localizar a seção de questões. "
            "Verifique se o arquivo contém 'PARTE 2' ou 'Questão 1'."
        )

    logger("Detectando questões automaticamente...")

    questions: List[DocxQuestion] = []
    current_numero: Optional[int] = None
    current_is_reserva: bool = False
    current_enunciado_parts: List[str] = []
    current_alternativas: Dict[str, str] = {}
    in_enunciado = False

    def flush():
        nonlocal current_numero, current_is_reserva
        nonlocal current_enunciado_parts, current_alternativas, in_enunciado
        if current_numero is None:
            return
        enunciado = _compact(" ".join(current_enunciado_parts))
        alts = dict(current_alternativas)
        label = f"R{current_numero}" if current_is_reserva else f"Q{current_numero}"
        if len(enunciado.split()) >= 3:
            block = QuestionBlock(
                numero=current_numero,
                tipo="ACESSO_DIRETO",
                enunciado=enunciado,
                alternativas=alts,
                texto_completo=enunciado,
            )
            questions.append(DocxQuestion(block=block, is_reserva=current_is_reserva, label=label))
        current_numero = None
        current_enunciado_parts = []
        current_alternativas = {}
        in_enunciado = False

    for text in paragraphs[parte2_idx + 1:]:
        if not text:
            continue

        parsed = _parse_questao_header(text)
        if parsed is not None:
            flush()
            current_numero, current_is_reserva = parsed
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

    principais = [q for q in questions if not q.is_reserva]
    reservas   = [q for q in questions if q.is_reserva]
    logger(f"{len(principais)} questões principais + {len(reservas)} reservas = {len(questions)} total.")
    return questions


# ─────────── Busca agressiva para Word ───────────

def _find_code_docx(
    page,
    questao: QuestionBlock,
    logger: Callable = print,
) -> Optional[MatchResult]:
    """Busca agressiva — todas as questões estão no Manager."""
    queries = build_queries_from_enunciado(questao.enunciado, questao.alternativas)
    total_alts = count_pdf_alternatives(questao.alternativas) or 4
    seen_codes: set[str] = set()
    best_media: Optional[tuple] = None
    best_baixa: Optional[tuple] = None
    query_count = 0
    max_score_seen = 0

    logger(f"  {len(queries)} queries geradas.")

    for q in queries[:DOCX_MAX_QUERIES]:
        query_count += 1

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

            for r in rows[:25]:
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

                ratio = num_alt / total_alts if total_alts else 0
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

            if best_media and best_media[0].score_enunciado >= 90:
                return best_media[0]

    result = (best_media[0] if best_media else None) or (best_baixa[0] if best_baixa else None)
    if not result:
        logger(f"  Não encontrado após {query_count} queries. Melhor score: {max_score_seen}%")
    return result


# ─────────── Extração principal ───────────

def run_docx_extraction(
    docx_path: str,
    logger: Callable = print,
) -> Dict:
    """
    Extrai códigos de TODAS as questões do .docx.
    Retorna dict com 'codes' (lista completa), 'principais' e 'reservas' separados.
    """
    from playwright.sync_api import sync_playwright

    if not Path(docx_path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {docx_path}")

    logger("=" * 50)
    logger("EXTRAÇÃO DE QUESTÕES DO WORD")
    logger("=" * 50)

    dq_list = parse_questoes_from_docx(docx_path, logger)
    total = len(dq_list)

    if not dq_list:
        raise RuntimeError("Nenhuma questão foi encontrada no documento.")

    if not Path(STORAGE_STATE).exists():
        raise RuntimeError(
            "Sessão do painel não encontrada. "
            "Use o botão 'Login Painel' para autenticar primeiro."
        )

    principais: List[str] = []
    reservas: List[str] = []
    found_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=30)
        context = browser.new_context(storage_state=STORAGE_STATE)
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        _ensure_logged_in_and_save_state(page, context, STORAGE_STATE)

        for idx, dq in enumerate(dq_list, 1):
            questao = dq.block
            preview = (questao.enunciado[:90] + "...") if len(questao.enunciado) > 90 else questao.enunciado
            tipo_label = "RESERVA" if dq.is_reserva else "PRINCIPAL"
            logger(f"[{idx}/{total}] {tipo_label} {dq.label}: {preview}")

            match = _find_code_docx(page, questao, logger)

            if match:
                found_count += 1
                logger(f"  ✓ ENCONTRADO: {match.code} (score={match.score_enunciado}%, {match.confianca}) [{found_count}/{total}]")
                if dq.is_reserva:
                    reservas.append(match.code)
                else:
                    principais.append(match.code)
            else:
                marker = f"{dq.label}_NAO_ENCONTRADO"
                logger(f"  ✗ NÃO ENCONTRADO [{found_count}/{total}]")
                if dq.is_reserva:
                    reservas.append(marker)
                else:
                    principais.append(marker)

        browser.close()

    logger(f"CONCLUÍDO: {found_count}/{total} códigos encontrados.")
    logger(f"  Principais: {len(principais)} | Reservas: {len(reservas)}")

    return {
        "codes": principais + reservas,
        "principais": principais,
        "reservas": reservas,
    }
