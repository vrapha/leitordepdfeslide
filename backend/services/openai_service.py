"""
OpenAI Service — substitui a automação do ChatGPT via browser.
Usa a API oficial da OpenAI para gerar os comentários das questões.
"""
import os
import re
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


def _param_rejeitado(error) -> str | None:
    """
    Extrai o nome do parâmetro que a API rejeitou num erro 400.
    Ex.: 'max_tokens', 'temperature'. Retorna None se não identificar.
    """
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        p = body.get("param")
        if p:
            return p
    # Fallback: procura o primeiro identificador entre aspas na mensagem
    m = re.search(r"'([a-zA-Z_]+)'", str(error))
    return m.group(1) if m else None


def query_openai(prompt: str, logger: Callable = print) -> str:
    """
    Envia o prompt para a OpenAI e retorna a resposta como texto.
    Requer OPENAI_API_KEY no ambiente. O modelo vem de OPENAI_MODEL.

    Compatível com modelos antigos (gpt-4o-mini) e da família GPT-5
    (gpt-5.4-mini): usa max_completion_tokens e remove automaticamente
    qualquer parâmetro que o modelo rejeitar (ex.: temperature).
    Retenta até 3 vezes em erros transitórios.
    """
    try:
        from openai import OpenAI, RateLimitError, APIError, BadRequestError
    except ImportError:
        raise RuntimeError("Pacote 'openai' não instalado. Adicione ao requirements.txt.")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY não configurada. Adicione a variável de ambiente no Railway."
        )

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_completion_tokens": 3000,
    }

    transient = 0   # erros transitórios (rate limit / API) — máx. 3
    strips = 0      # parâmetros removidos por incompatibilidade — máx. 4

    while True:
        try:
            response = client.chat.completions.create(**params)
            return response.choices[0].message.content or ""
        except BadRequestError as e:
            param = _param_rejeitado(e)
            # Só remove parâmetros opcionais — nunca model/messages
            if param and param in params and param not in ("model", "messages") and strips < 4:
                strips += 1
                params.pop(param, None)
                logger(f"Modelo {model} não aceita '{param}'. Removendo e tentando novamente.")
                continue
            raise RuntimeError(f"OpenAI rejeitou a requisição (400): {e}")
        except RateLimitError:
            transient += 1
            if transient >= 3:
                raise RuntimeError("OpenAI API: rate limit persistente após 3 tentativas.")
            wait = transient * 20
            logger(f"Rate limit da OpenAI. Aguardando {wait}s...")
            time.sleep(wait)
        except APIError as e:
            transient += 1
            if transient >= 3:
                raise RuntimeError(f"OpenAI API falhou após 3 tentativas: {e}")
            logger(f"Erro da API OpenAI (tentativa {transient}). Tentando novamente...")
            time.sleep(5)
