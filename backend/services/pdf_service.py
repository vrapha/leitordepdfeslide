"""
PDF Service — Extração de códigos de questões de PDFs acadêmicos.
Portado do robo_pdf_para_codigos.py. Usa Playwright para acessar o painel web.
"""
from __future__ import annotations

import os
import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import fitz  # PyMuPDF
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from rapidfuzz import fuzz
from unidecode import unidecode

QUESTIONS_URL = "https://manager.eumedicoresidente.com.br/admin/resources/Question"
SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
STORAGE_STATE = str(SESSIONS_DIR / "storage_state.json")

# Matching
TOKEN_SET_ENUNCIADO = 85
PARTIAL_ENUNCIADO = 88
ALTERNATIVA_TOKEN_SET = 80
ALTERNATIVA_PARTIAL = 83

MAX_PAGES_GENERIC = 14
MAX_PAGES_SPECIFIC = 6
MAX_QUERY_CHARS = 1400
MAX_QUERIES_PER_QUESTION = 80   # era 50 — mais tentativas com as novas queries
MAX_SEEN_CODES_BEFORE_STOP = 30
SMART_STOP_AFTER = 20           # era 12 — desistia cedo demais
MIN_SCORE_TO_CONTINUE = 50      # era 60 — desistia com score razoável
QUICK_STOP_AFTER_QUERIES = 10
QUICK_STOP_MIN_SCORE = 88
EARLY_STOP_IF_GOOD_MEDIA = True
MEDIA_EARLY_MIN_ENUN = 90
MEDIA_EARLY_MIN_ALT_RATIO = 0.70
SPECIALTY_TD_INDEX = 3
MIN_WORDS_ENUNCIADO = 4

STOPWORDS = {
    "a", "o", "os", "as", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "e", "ou", "para", "por", "com", "sem", "ao", "aos", "à", "às",
    "que", "qual", "quais", "quando", "onde", "como",
    "assinale", "marque", "indique", "alternativa", "correta", "incorreta", "errada",
    "sobre", "respeito", "relacao", "relacionada", "paciente", "correto", "afirmar",
}


# ─────────── Utilitários ───────────

def compact_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = unidecode(s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_for_comparison(s: str) -> str:
    s = normalize_text(s)
    for palavra in ["lembre se", "observe", "considere", "assinale", "marque",
                    "portanto", "logo", "assim", "correta", "incorreta"]:
        s = s.replace(palavra, " ")
    s = re.sub(r"\b\d+\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def count_pdf_alternatives(alts: Dict[str, str]) -> int:
    return len({alts[k].strip() for k in ["A", "B", "C", "D", "E"] if k in alts and alts[k].strip()})


def is_certo_errado_alts(alts: Dict[str, str]) -> bool:
    if not alts:
        return False
    vals = " ".join((alts.get("A", ""), alts.get("B", ""))).upper()
    return "CERTO" in vals or "ERRADO" in vals


# ─────────── Sumário / range ───────────

def find_section_pages_via_sumario(pdf_path: str) -> Tuple[int, int]:
    doc = fitz.open(pdf_path)
    max_scan = min(12, doc.page_count)
    parts = [doc.load_page(i).get_text("text") or "" for i in range(max_scan)]
    doc.close()
    blob = "\n".join(parts)

    m_q = re.search(r"QUEST[ÕO]ES\s+EXTRAS\s+\.{2,}\s*(\d{1,4})\s*$", blob, re.I | re.M)
    m_c = re.search(r"COMENT[ÁA]RIOS\s+E\s+GABARITOS\s+\.{2,}\s*(\d{1,4})\s*$", blob, re.I | re.M)

    if not m_q or not m_c:
        raise RuntimeError(
            "Não localizei no SUMÁRIO:\n"
            f" - QUESTÕES EXTRAS: {'OK' if m_q else 'NÃO ENCONTRADO'}\n"
            f" - COMENTÁRIOS E GABARITOS: {'OK' if m_c else 'NÃO ENCONTRADO'}\n"
            "Verifique se o PDF possui esse sumário na estrutura esperada."
        )

    start_q = int(m_q.group(1))
    start_c = int(m_c.group(1))
    if start_c < start_q:
        raise RuntimeError(f"SUMÁRIO inconsistente: comentários ({start_c}) < questões ({start_q}).")
    return start_q, start_c


def fix_pdf_text(text: str) -> str:
    """Corrige artefatos comuns de extração de PDF."""
    # Palavras hifenizadas no final da linha: "dia-\nbetes" → "diabetes"
    text = re.sub(r"([a-záéíóúàâêîôûãõç])-\n([a-záéíóúàâêîôûãõç])", r"\1\2", text, flags=re.I)
    # Hifenização sem acento
    text = re.sub(r"([a-z])-\n([a-z])", r"\1\2", text)
    # Múltiplas quebras de linha seguidas viram uma só
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_text_from_page_range(pdf_path: str, start: int, end_excl: int) -> str:
    doc = fitz.open(pdf_path)
    end = min(end_excl, doc.page_count)
    parts = [doc.load_page(i).get_text("text") or "" for i in range(start, end)]
    doc.close()
    full = "\n".join(parts)
    # Aplica correções de artefatos antes de tudo
    full = fix_pdf_text(full)
    trunc = "COMENTÁRIOS E GABARITOS"
    if trunc in full:
        full = full[: full.find(trunc)]
    return full


# ─────────── Parsing questões ───────────

@dataclass
class QuestionBlock:
    numero: Optional[int]
    tipo: str
    enunciado: str
    alternativas: Dict[str, str]
    texto_completo: str


def extract_alternativas(texto: str) -> Dict[str, str]:
    alternativas: Dict[str, str] = {}
    realloc = {k: [l for l in "ABCDE" if l != k] for k in "ABCDE"}
    partes = re.split(r"(?:(?:\r?\n)|(?:\s+))([A-E])[\)\.]\s+|(?:(?:\r?\n)|(?:\s+))([A-E])\s*-\s*", texto or "")
    letra_atual = None
    for parte in partes:
        if parte is None:
            continue
        parte = parte.strip()
        if parte in list("ABCDE"):
            letra_atual = parte
            continue
        if letra_atual and parte:
            valor = compact_spaces(parte)
            if letra_atual in alternativas:
                for fb in realloc.get(letra_atual, []):
                    if fb not in alternativas:
                        alternativas[fb] = valor
                        break
                else:
                    alternativas[letra_atual] = compact_spaces(alternativas[letra_atual] + " " + valor)
            else:
                alternativas[letra_atual] = valor
    for k in ["A", "B"]:
        if k in alternativas:
            v = alternativas[k].strip().upper()
            if "CERTO" in v:
                alternativas[k] = "CERTO"
            elif "ERRADO" in v:
                alternativas[k] = "ERRADO"
    return alternativas


def extract_questao_completa(block: str) -> QuestionBlock:
    texto_completo = (block or "").strip()
    numero = None
    m = re.match(r"^\s*(\d+)\s*\.\s", texto_completo)
    if m:
        numero = int(m.group(1))

    tipo = "ACESSO_DIRETO" if "acesso direto" in texto_completo.lower() else "ESPECIALIDADE"

    texto = re.sub(r"^\s*\d+\.\s*", "", texto_completo)
    texto = re.sub(r"^.*?\bACESSO\s+DIRETO\b\s*\.\s*", "", texto, flags=re.I | re.S)

    match_alts = re.search(r"(?:\r?\n)\s*([A-E][\)\.]\s*|[A-E]\s*-\s*)", texto)
    if not match_alts:
        match_alts = re.search(r"(\s+[A-E][\)\.]\s+)", texto)

    if match_alts:
        enunciado = texto[: match_alts.start()].strip()
        texto_alts = "\n" + texto[match_alts.start():].strip()
    else:
        enunciado = texto.strip()
        texto_alts = ""

    enunciado = re.sub(r"\bacesso\s+direto\b", "", enunciado, flags=re.I)
    enunciado = re.sub(r"^QUEST[ÕO]ES\s+EXTRAS\s*", "", enunciado, flags=re.I | re.M)
    # Remove preâmbulo SOMENTE se for curto (≤ 8 palavras) e contiver ano — evita remover conteúdo real
    lines = enunciado.splitlines()
    if lines:
        first = lines[0].strip()
        if len(first.split()) <= 8 and re.search(r"20\d{2}", first):
            enunciado = "\n".join(lines[1:])
    enunciado = compact_spaces(enunciado)
    alternativas = extract_alternativas(texto_alts)

    return QuestionBlock(
        numero=numero,
        tipo=tipo,
        enunciado=enunciado,
        alternativas=alternativas,
        texto_completo=texto_completo,
    )


def split_blocks_by_numbering(text: str) -> List[str]:
    text2 = re.sub(r"(?m)^\s*(\d+)\s*\.\s*", r"\n@@QSTART@@\1. ", text or "")
    parts = text2.split("@@QSTART@@")
    return [p.strip() for p in parts if p.strip() and re.match(r"^\d+\.\s", p.strip())]


def parse_questoes_from_pdf(pdf_path: str, logger: Callable = print) -> Tuple[List[QuestionBlock], List[QuestionBlock]]:
    start_q_1, start_c_1 = find_section_pages_via_sumario(pdf_path)
    logger(f"SUMÁRIO: págs {start_q_1} até {start_c_1 - 1}")

    text = extract_text_from_page_range(pdf_path, start_q_1 - 1, start_c_1)
    blocks = split_blocks_by_numbering(text)
    logger(f"{len(blocks)} questões encontradas no intervalo.")

    acesso_direto: List[QuestionBlock] = []
    outras: List[QuestionBlock] = []
    auto_num = 1

    for block in blocks:
        try:
            q = extract_questao_completa(block)
            if q.numero is None:
                q.numero = auto_num
            auto_num = q.numero + 1

            if len(q.enunciado.split()) < MIN_WORDS_ENUNCIADO:
                continue
            if len(q.alternativas) < 3:
                if not (len(q.alternativas) >= 2 and is_certo_errado_alts(q.alternativas)):
                    continue

            (acesso_direto if q.tipo == "ACESSO_DIRETO" else outras).append(q)
        except Exception as e:
            logger(f"Erro ao parsear bloco: {e}")

    return acesso_direto, outras


# ─────────── Queries ───────────

def build_queries_from_enunciado(
    enunciado: str,
    alternatives: Dict[str, str] | None = None,
) -> List[str]:
    """
    Constrói queries de busca em múltiplas estratégias, ordenadas por especificidade.

    Melhorias v2:
    - step=1 para janelas menores (cobertura total)
    - janelas de 5-7 palavras para enunciados curtos
    - variante sem acento (unidecode) de cada query
    - última frase do enunciado (pergunta específica) como prioridade alta
    - termos médicos raros (palavras longas) como âncoras
    - fallback com texto das alternativas
    """
    text = compact_spaces(enunciado or "")
    if not text:
        return []

    # Variante sem acentos (para diferenças de normalização entre PDF e site)
    text_nd = unidecode(text)

    queries: list[tuple[str, int]] = []
    seen: set[str] = set()

    def add_unique(q: str, priority: int = 5):
        q = re.sub(r"^[^\w]+|[^\w]+$", "", compact_spaces(q)).strip()
        if not q or q.lower() in seen or len(q.split()) < 3:
            return
        if len(q) > MAX_QUERY_CHARS:
            q = q[:MAX_QUERY_CHARS].rstrip()
        seen.add(q.lower())
        queries.append((q, priority))

    words = text.split()
    words_nd = text_nd.split()
    n = len(words)

    # ── 1. Última frase (a pergunta em si — mais específica e única) ──────────
    sentences = re.split(r"[.!?]\s+", text)
    sentences = [s.strip() for s in sentences if len(s.strip().split()) >= 4]
    if len(sentences) >= 1:
        add_unique(sentences[-1], priority=1)           # última frase
        add_unique(unidecode(sentences[-1]), priority=1)
    if len(sentences) >= 2:
        add_unique(sentences[-2], priority=1)           # penúltima frase

    # ── 2. Termos médicos raros (palavras longas ≥ 8 letras, não stopwords) ──
    med_words = [w for w in words if len(w) >= 8 and w.lower() not in STOPWORDS
                 and re.match(r"^[a-záéíóúàâêîôûãõç]+$", w, re.I)]
    for i in range(len(med_words)):
        if i + 2 < len(med_words):
            add_unique(f"{med_words[i]} {med_words[i+1]} {med_words[i+2]}", priority=1)
        if i + 1 < len(med_words):
            add_unique(f"{med_words[i]} {med_words[i+1]}", priority=1)

    # ── 3. Âncoras numéricas (dosagens, idades, valores laboratoriais) ────────
    anchors = re.findall(r"\b[\w]+\s*[=:]\s*\d+(?:[.,]\d+)?(?:\s*\w+)?\b", text)
    for anchor in anchors:
        add_unique(anchor, priority=1)

    # ── 4. Janelas deslizantes — step=2 para 12-15 palavras ──────────────────
    for size in [15, 12]:
        if n >= size:
            for start in range(0, n - size + 1, 2):           # step=2 (era 3)
                prio = 1 if start == 0 else 2
                add_unique(" ".join(words[start: start + size]), priority=prio)
                add_unique(" ".join(words_nd[start: start + size]), priority=prio + 1)

    # ── 5. Janelas médias — step=1 (cobertura total) ─────────────────────────
    for size in [10, 9, 8]:
        if n >= size:
            for start in range(0, n - size + 1, 1):           # step=1 (era 3)
                prio = 2 if start == 0 else 3
                add_unique(" ".join(words[start: start + size]), priority=prio)
                add_unique(" ".join(words_nd[start: start + size]), priority=prio + 1)

    # ── 6. Janelas curtas — para enunciados com poucos palavras ──────────────
    for size in [7, 6, 5]:
        if n >= size:
            for start in range(0, n - size + 1, 1):
                prio = 3 if start == 0 else 4
                add_unique(" ".join(words[start: start + size]), priority=prio)

    # ── 7. Início e fim do enunciado ─────────────────────────────────────────
    if n >= 6:
        add_unique(" ".join(words[:6]), priority=3)
        add_unique(" ".join(words[-6:]), priority=3)
        add_unique(" ".join(words_nd[:6]), priority=4)

    # ── 8. Fallback: texto das alternativas (último recurso) ─────────────────
    if alternatives:
        for letter in ["A", "B", "C", "D", "E"]:
            alt_text = (alternatives.get(letter) or "").strip()
            alt_words = alt_text.split()
            if len(alt_words) >= 6:
                add_unique(" ".join(alt_words[:10]), priority=5)
                add_unique(unidecode(" ".join(alt_words[:8])), priority=5)

    queries.sort(key=lambda x: x[1])
    return [q[0] for q in queries]


# ─────────── Site structs ───────────

@dataclass
class SiteQuestion:
    code: str
    enunciado: str
    alternativas: Dict[str, str]
    is_acesso_direto: bool
    especialidade: str


@dataclass
class MatchResult:
    code: str
    score_enunciado: int
    num_alternativas: int
    confianca: str
    is_acesso_direto: bool
    especialidade: str


def goto_filter_page(page, q: str, page_num: int):
    url = f"{QUESTIONS_URL}?page={page_num}&filters.description={quote_plus(q)}"
    page.goto(url, wait_until="domcontentloaded", timeout=60000)


def wait_results(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_function(
        """() => {
            const trs = document.querySelectorAll('table tbody tr');
            if (trs && trs.length > 0) return true;
            const t = document.body ? document.body.innerText : '';
            if (t.includes('Nenhum') && t.includes('registro')) return true;
            if (t.includes('No records')) return true;
            return false;
        }""",
        timeout=25000,
    )


def parse_listagem_texto(raw: str) -> Tuple[str, Dict[str, str], bool]:
    lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
    is_ad = any("ACESSO DIRETO" in l.upper() for l in lines[:3])
    while lines and lines[0].startswith("(") and lines[0].endswith(")"):
        lines.pop(0)

    alternativas: Dict[str, str] = {}
    enun_parts: List[str] = []
    alt_pat = re.compile(r"^([A-E])[\)\.\-]\s*(.+)$")
    ce_pat = re.compile(r"^(A|B)[\)\.\-]\s*(CERTO|ERRADO)\.?\s*$", re.I)
    in_alts = False

    for l in lines:
        m = alt_pat.match(l)
        if m:
            in_alts = True
            alternativas[m.group(1)] = compact_spaces(m.group(2))
            continue
        m2 = ce_pat.match(l)
        if m2:
            in_alts = True
            alternativas[m2.group(1).upper()] = m2.group(2).upper()
            continue
        if not in_alts:
            enun_parts.append(l)

    return compact_spaces(" ".join(enun_parts)), alternativas, is_ad


def validate_question_match(pdf_q: QuestionBlock, site_q: SiteQuestion) -> Tuple[bool, int, int]:
    a_n = normalize_text(pdf_q.enunciado)
    b_n = normalize_text(site_q.enunciado)
    a_x = normalize_for_comparison(pdf_q.enunciado)
    b_x = normalize_for_comparison(site_q.enunciado)

    ts = max(fuzz.token_set_ratio(a_n, b_n), fuzz.token_set_ratio(a_x, b_x))
    pr = max(fuzz.partial_ratio(a_n, b_n), fuzz.partial_ratio(a_x, b_x))

    enun_ok = ts >= TOKEN_SET_ENUNCIADO or pr >= PARTIAL_ENUNCIADO or ts >= 82
    if not enun_ok:
        return False, int(ts), 0

    alts_ok = 0
    for letra in list("ABCDE"):
        if letra not in pdf_q.alternativas or letra not in site_q.alternativas:
            continue
        pa = normalize_text(pdf_q.alternativas[letra])
        sa = normalize_text(site_q.alternativas[letra])
        px = normalize_for_comparison(pdf_q.alternativas[letra])
        sx = normalize_for_comparison(site_q.alternativas[letra])
        ts_a = max(fuzz.token_set_ratio(pa, sa), fuzz.token_set_ratio(px, sx))
        pr_a = max(fuzz.partial_ratio(pa, sa), fuzz.partial_ratio(px, sx))
        if ts_a >= ALTERNATIVA_TOKEN_SET or pr_a >= ALTERNATIVA_PARTIAL or ts_a >= 78:
            alts_ok += 1

    if is_certo_errado_alts(pdf_q.alternativas):
        return alts_ok >= 1 and ts >= 80, int(ts), alts_ok

    total = count_pdf_alternatives(pdf_q.alternativas)

    # Thresholds mais lenientes: PDFs frequentemente extraem alternativas com ruído
    # (hifenização, quebras de linha, formatação) — não punir por 1 alternativa ruim
    if total <= 3:
        min_n, near_n, thr = 2, 1, 80
    elif total == 4:
        min_n, near_n, thr = 2, 1, 82   # era (3, 2, 83) — exigia demais
    else:
        min_n, near_n, thr = 3, 2, 83   # era (4, 3, 86) — exigia 4/5 corretas

    ok = alts_ok >= min_n or (alts_ok >= near_n and ts >= thr)

    # Fallbacks por score alto de enunciado
    if not ok and ts >= 88 and alts_ok >= 1:
        ok = True
    if not ok and ts >= 92 and alts_ok >= 0:    # enunciado quase perfeito → confiar
        ok = True
    if not ok and ts >= 95:                      # enunciado idêntico → confiar sempre
        ok = True

    return ok, int(ts), alts_ok


def find_code_for_question(
    page,
    questao: QuestionBlock,
    logger: Callable = print,
) -> Optional[MatchResult]:
    # Passa alternativas para o builder — usado como fallback de última instância
    queries = build_queries_from_enunciado(questao.enunciado, questao.alternativas)
    total_pdf = count_pdf_alternatives(questao.alternativas) or 5
    seen_codes: set[str] = set()
    best_media: Optional[tuple[MatchResult, int]] = None
    best_baixa: Optional[tuple[MatchResult, int]] = None
    query_count = 0
    max_score_seen = 0
    logger(f"  [{questao.numero}] {len(queries)} queries geradas para busca.")

    for q in queries[:MAX_QUERIES_PER_QUESTION]:
        query_count += 1
        limit_pages = MAX_PAGES_GENERIC if len(q.split()) <= 2 else MAX_PAGES_SPECIFIC
        per_page = 50 if len(q.split()) <= 2 else 25

        for pnum in range(1, limit_pages + 1):
            goto_filter_page(page, q, pnum)
            wait_results(page)

            rows = page.evaluate(
                f"""() => {{
                    const out = [];
                    for (const tr of document.querySelectorAll('table tbody tr')) {{
                        const tds = tr.querySelectorAll('td');
                        if (!tds || tds.length < {SPECIALTY_TD_INDEX + 1}) continue;
                        const code = (tds[1]?.innerText || '').trim();
                        const desc = (tds[2]?.innerText || '').trim();
                        const esp  = (tds[{SPECIALTY_TD_INDEX}]?.innerText || '').trim();
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
                if not enun or len(alts) < 2:
                    continue
                sq = SiteQuestion(code, enun, alts, is_ad, esp)
                match_ok, score, num_alt = validate_question_match(questao, sq)
                max_score_seen = max(max_score_seen, score)
                if not match_ok:
                    continue

                ratio = num_alt / total_pdf
                if score >= 90 and ratio >= 0.75:
                    confianca = "ALTA"
                elif score >= 80 and ratio >= 0.70:
                    confianca = "MEDIA"
                else:
                    confianca = "BAIXA"

                result = MatchResult(code, score, num_alt, confianca, is_ad, esp)
                rank = (1000 if is_ad else 0) + score * 10 + num_alt

                if confianca == "ALTA":
                    return result
                if confianca == "MEDIA":
                    if best_media is None or rank > best_media[1]:
                        best_media = (result, rank)
                    if query_count <= QUICK_STOP_AFTER_QUERIES and score >= QUICK_STOP_MIN_SCORE:
                        return result
                else:
                    if best_baixa is None or rank > best_baixa[1]:
                        best_baixa = (result, rank)

            if EARLY_STOP_IF_GOOD_MEDIA and best_media:
                bm = best_media[0]
                if bm.score_enunciado >= MEDIA_EARLY_MIN_ENUN and (bm.num_alternativas / total_pdf) >= MEDIA_EARLY_MIN_ALT_RATIO:
                    return bm

            if best_baixa and best_baixa[0].score_enunciado >= 98 and query_count >= 3:
                return best_baixa[0]

            if len(seen_codes) >= MAX_SEEN_CODES_BEFORE_STOP and best_media:
                break

        if query_count >= SMART_STOP_AFTER and max_score_seen < MIN_SCORE_TO_CONTINUE:
            logger(f"  [{questao.numero}] Smart Stop após {query_count} queries. Melhor score: {max_score_seen}%")
            break

    result = (best_media[0] if best_media else None) or (best_baixa[0] if best_baixa else None)
    if not result:
        logger(f"  [{questao.numero}] Não encontrado. Melhor score visto: {max_score_seen}% ({query_count} queries testadas)")
    return result


# ─────────── Main ───────────

def _ensure_logged_in_and_save_state(page, context, storage_state_path: str):
    page.goto(QUESTIONS_URL, wait_until="domcontentloaded", timeout=60000)
    url = (page.url or "").lower()
    is_login = "/admin/login" in url or "/login" in url or url.endswith("/login")
    if is_login:
        raise RuntimeError(
            "Login necessário. Use o botão 'Login Painel' para autenticar primeiro."
        )
    sp = Path(storage_state_path)
    sp.parent.mkdir(parents=True, exist_ok=True)
    if not sp.exists():
        context.storage_state(path=str(sp))


def run_pdf_extraction(
    pdf_path: str,
    logger: Callable = print,
    headless: bool = False,
    target_encontradas: int = 30,
) -> List[str]:
    """
    Função principal: extrai códigos do PDF e retorna lista de strings.
    """
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF não encontrado: {pdf_path}")

    logger("=" * 50)
    logger("EXTRAÇÃO DE QUESTÕES DO PDF")
    logger("=" * 50)

    ad_questions, outras_questions = parse_questoes_from_pdf(pdf_path, logger)
    logger(f"ACESSO DIRETO: {len(ad_questions)} | ESP: {len(outras_questions)}")

    if not Path(STORAGE_STATE).exists():
        raise RuntimeError(
            "Sessão do painel não encontrada. "
            "Use o botão 'Login Painel' para autenticar primeiro."
        )

    ad_nao_encontradas: List[int] = []
    results: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=30)
        context = browser.new_context(storage_state=STORAGE_STATE)
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        _ensure_logged_in_and_save_state(page, context, STORAGE_STATE)

        all_questions = ad_questions + outras_questions
        found_count = 0

        for idx, questao in enumerate(all_questions, 1):
            if found_count >= target_encontradas:
                break

            numero = questao.numero or idx
            tipo = "AD" if questao.tipo == "ACESSO_DIRETO" else "ESP"
            preview = (questao.enunciado[:100] + "...") if len(questao.enunciado) > 100 else questao.enunciado
            logger(f"[{idx}/{len(all_questions)}] {tipo} Q{numero}: {preview}")

            match = find_code_for_question(page, questao, logger)

            if match:
                categoria = "ACESSO DIRETO" if questao.tipo == "ACESSO_DIRETO" else "ESP"
                codigo = f"{match.code} ({categoria}, Q{numero} PDF)"
                results.append(codigo)
                found_count += 1
                logger(f"  ENCONTRADO: {codigo} ({match.confianca}) [{found_count}/{target_encontradas}]")
            else:
                logger(f"  NÃO ENCONTRADO [{found_count}/{target_encontradas}]")
                if questao.tipo == "ACESSO_DIRETO":
                    ad_nao_encontradas.append(numero)

        browser.close()

    for n in ad_nao_encontradas:
        results.append(f"Q{n} ACESSO DIRETO (NÃO ENCONTRADA)")

    logger(f"CONCLUÍDO: {len(results)} códigos extraídos.")
    return results
