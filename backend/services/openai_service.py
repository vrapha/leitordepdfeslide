"""
OpenAI Service — substitui a automação do ChatGPT via browser.
Usa a API oficial da OpenAI para gerar os comentários das questões.
"""
import os
import time
from typing import Callable


_SYSTEM_MESSAGE = (
    "Você é um professor de medicina com 20 anos de experiência em preparação para provas "
    "de residência médica brasileiras. Escreve comentários técnicos, didáticos e diretos, "
    "sem floreios, focados no que mais cai nas bancas. "
    "Usa apenas fontes do Ministério da Saúde, SBC, CFM e diretrizes internacionais consagradas. "
    "NUNCA usa markdown, asteriscos, hífens como marcadores ou qualquer formatação especial. "
    "Escreve apenas texto puro com quebras de linha."
)


def query_openai(prompt: str, logger: Callable = print) -> str:
    """
    Envia o prompt para a OpenAI e retorna a resposta como texto.
    Requer OPENAI_API_KEY no ambiente.
    Retenta até 3 vezes em caso de erro transitório.
    """
    try:
        from openai import OpenAI, RateLimitError, APIError
    except ImportError:
        raise RuntimeError("Pacote 'openai' não instalado. Adicione ao requirements.txt.")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY não configurada. Adicione a variável de ambiente no Railway."
        )

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=3000,
            )
            return response.choices[0].message.content or ""
        except RateLimitError:
            wait = attempt * 20
            logger(f"Rate limit da OpenAI. Aguardando {wait}s...")
            time.sleep(wait)
        except APIError as e:
            if attempt < 3:
                logger(f"Erro da API OpenAI (tentativa {attempt}). Tentando novamente...")
                time.sleep(5)
            else:
                raise RuntimeError(f"OpenAI API falhou após 3 tentativas: {e}")

    raise RuntimeError("OpenAI API não respondeu após 3 tentativas.")
