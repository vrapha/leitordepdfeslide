"""
PPT Service — Orquestra os 4 parsers em cascata (Hybrid V9) e o bot ChatGPT.
Portado do main.py original sem dependências Windows.
"""
import os
import re
from pathlib import Path
from typing import Callable

from parsers.ppt_parser import PPTParser
from parsers.ppt_robust_parser import RobustPPTXParser
from parsers.ppt_xml_parser import PPTXMLParser


EMR_BOILERPLATE = [
    r"LEMBRE-SE DE CLASSIFICAR AS QUESTÕES",
    r"Link do banco:",
    r"Senha:",
    r"TUTORIAL PARA CLASSIFICAÇÃO",
    r"LISTRA DE TEMAS PARA CLASSIFICAÇÃO",
    r"SEU EMAIL",
]


def clean_emr_boilerplate(text: str) -> str:
    if not text:
        return text
    for pattern in EMR_BOILERPLATE:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def analyze_ppt(
    ppt_path: str,
    manual_gabarito_text: str | None = None,
    logger: Callable = print,
) -> list[dict]:
    """
    Analisa PPTX com 4 parsers em cascata (Hybrid V9):
    1. PPTParser (texto + coordenadas)
    2. RobustPPTXParser (XML – PRIMÁRIO)
    3. PPTXMLParser (fallback XML com shapes nomeados)
    """
    if not os.path.exists(ppt_path):
        logger(f"Arquivo não encontrado: {ppt_path}")
        return []

    logger(f"Analisando: {Path(ppt_path).name}")

    # Salva gabarito manual se fornecido
    gabarito_path: str | None = None
    if manual_gabarito_text and manual_gabarito_text.strip():
        gabarito_path = str(Path(ppt_path).parent / "gabarito.txt")
        try:
            with open(gabarito_path, "w", encoding="utf-8") as f:
                f.write(manual_gabarito_text)
            logger("Gabarito manual salvo.")
        except Exception as e:
            logger(f"Erro ao salvar gabarito: {e}")
            gabarito_path = None

    # 1. Parser padrão (texto + conteúdo)
    slides_data: list[dict] = []
    try:
        parser = PPTParser(ppt_path)
        slides_data = parser.get_slide_data(gabarito_path)
        for item in slides_data:
            item["question"] = clean_emr_boilerplate(item["question"])
        logger(f"Parser padrão: {len(slides_data)} slides encontrados.")
    except Exception as e:
        logger(f"Erro no parser padrão: {e}")
        return []

    # 2. RobustXML (PRIMÁRIO — maior precisão)
    try:
        logger("Executando RobustXML Parser (PRIMÁRIO)...")
        robust_parser = RobustPPTXParser(ppt_path, logger)
        robust_answers = robust_parser.analyze()
        count = 0
        for item in slides_data:
            idx = item["slide_index"]
            if idx in robust_answers:
                item["correct_answer"] = robust_answers[idx]
                count += 1
        logger(f"RobustXML aplicou {count} respostas.")
    except Exception as e:
        logger(f"Erro no RobustXML: {e}")

    # 3. Fallback XMLParser (shapes nomeados)
    missing = [item for item in slides_data if not item.get("correct_answer")]
    if missing:
        try:
            logger(f"Executando XMLParser (fallback para {len(missing)} faltantes)...")
            xml_parser = PPTXMLParser(ppt_path)
            xml_answers = xml_parser.analyze()
            count = 0
            for item in slides_data:
                idx = item["slide_index"]
                if idx in xml_answers and not item.get("correct_answer"):
                    item["correct_answer"] = xml_answers[idx]
                    count += 1
            logger(f"XMLParser preencheu {count} respostas.")
        except Exception as e:
            logger(f"Erro no XMLParser: {e}")

    return slides_data


def build_prompt(question: str, alternatives: list[str], correct: str) -> str:
    """Constrói o prompt para o ChatGPT (mesmo formato do original)."""
    letters = ["A", "B", "C", "D", "E"]
    formatted_alts = []
    for i, alt in enumerate(alternatives):
        if len(alt) > 2 and alt[1] in [")", "."] and alt[0].upper() in letters:
            formatted_alts.append(alt)
        else:
            letter = letters[i] if i < len(letters) else f"Alt {i+1}"
            formatted_alts.append(f"{letter}) {alt}")

    alts_str = "\n".join(formatted_alts)
    is_annulled = str(correct).upper() == "ANULADA"

    prompt = (
        "Você é um professor especialista na preparação para provas de residência médica. "
        "Seu objetivo é escrever um comentário didático, técnico e profundo sobre uma questão "
        "de múltipla escolha. Utilize apenas fontes do Ministério da Saúde e das principais "
        "diretrizes nacionais e internacionais.\n\n"
        "REGRAS OBRIGATÓRIAS DE FORMATAÇÃO:\n"
        "- Texto puro, sem markdown, sem asteriscos, sem hífens como marcadores\n"
        "- Use apenas texto simples com quebras de linha\n"
        "- Siga exatamente os rótulos abaixo\n\n"
        "ESTRUTURA OBRIGATÓRIA:\n\n"
        "Dica de Prova:\n"
        "Escreva um macete clínico prático e memorável com aproximadamente 60 palavras. "
        "Use linguagem direta como 'tempo é músculo', 'pense em X quando ver Y'. "
        "Seja específico ao tema da questão. A dica deve ser aplicada em segundos durante a prova.\n\n"
        "Resumo do Tema:\n"
        "Escreva um parágrafo contínuo com aproximadamente 300 palavras. "
        "OBRIGATÓRIO: referencie os dados clínicos específicos do enunciado (achados do ECG, "
        "localização, artéria envolvida, valores, etc.). "
        "Explique fisiopatologia, diagnóstico e tratamento com base nas diretrizes. "
        "Cite prazos e condutas específicas. "
        "Finalize com o ponto mais cobrado em provas sobre este tema.\n\n"
        "Comentário Alternativa por Alternativa:\n"
        "Use sempre o feminino: 'incorreta' ou 'correta' (alternativa é feminino). "
        "Para cada letra, escreva ~40 palavras com raciocínio clínico específico.\n"
        "Letra A: incorreta/correta. [explicação]\n"
        "Letra B: incorreta/correta. [explicação]\n"
        "Letra C: incorreta/correta. [explicação]\n"
        "Letra D: incorreta/correta. [explicação]\n"
        "Letra E: incorreta/correta. [explicação, se houver]\n\n"
        "Resposta correta: Letra X\n\n"
        "QUESTÃO:\n" + question + "\n\n"
        "ALTERNATIVAS:\n" + alts_str + "\n\n"
    )

    if is_annulled:
        prompt += "questão anulada"
    else:
        prompt += f"Gabarito: {correct}\n"

    return prompt


def save_response_to_notes(parser: PPTParser, slide_idx: int, response: str, output_file: str):
    """Salva a resposta nas notas do slide, sempre com Especialidade/Assunto em branco no topo."""
    slide = parser.prs.slides[slide_idx]
    notes_slide = slide.notes_slide
    text_frame = notes_slide.notes_text_frame
    current_notes = text_frame.text
    prefix = "\n\n" if current_notes else ""
    # Especialidade e Assunto sempre em branco — professor preenche depois
    header = "Especialidade:\n\nAssunto:\n\n"
    full_text = prefix + header + response
    text_frame.text = current_notes

    for line in full_text.split("\n"):
        p = text_frame.add_paragraph()
        if "Especialidade:" in line:
            parts = line.split("Especialidade:", 1)
            if parts[0]:
                p.add_run().text = parts[0]
            r = p.add_run()
            r.text = "Especialidade:"
            r.font.bold = True
            if parts[1]:
                p.add_run().text = parts[1]
        elif "Assunto:" in line:
            parts = line.split("Assunto:", 1)
            if parts[0]:
                p.add_run().text = parts[0]
            r = p.add_run()
            r.text = "Assunto:"
            r.font.bold = True
            if parts[1]:
                p.add_run().text = parts[1]
        else:
            p.text = line

    parser.save(output_file)
