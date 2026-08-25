"""
LLM Service — gera os comentários das questões via OpenRouter.
Usa o SDK da OpenAI apontado para a API do OpenRouter (compatível).
"""
import os
import re
import time
from typing import Callable


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

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


def _resolver_modelo() -> str:
    """
    Nome do modelo no formato do OpenRouter (`provedor/modelo`).
    Aceita OPENROUTER_MODEL ou, por compatibilidade, OPENAI_MODEL.
    Se vier sem provedor (ex.: 'gpt-4o-mini'), assume 'openai/'.
    """
    model = (
        os.environ.get("OPENROUTER_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "openai/gpt-4o-mini"
    ).strip()
    if "/" not in model:
        model = f"openai/{model}"
    return model


def query_openai(prompt: str, logger: Callable = print) -> str:
    """
    Envia o prompt para o OpenRouter e retorna a resposta como texto.
    Requer OPENROUTER_API_KEY no ambiente. O modelo vem de OPENROUTER_MODEL.

    Remove automaticamente qualquer parâmetro que o modelo rejeitar
    (ex.: temperature) e retenta até 3 vezes em erros transitórios.
    """
    try:
        from openai import OpenAI, RateLimitError, APIError, BadRequestError
    except ImportError:
        raise RuntimeError("Pacote 'openai' não instalado. Adicione ao requirements.txt.")

    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY não configurada. Adicione a variável de ambiente no Railway."
        )

    model = _resolver_modelo()
    base_url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL)

    # Headers opcionais do OpenRouter (ranking/identificação da app)
    default_headers = {}
    referer = os.environ.get("OPENROUTER_SITE_URL", "")
    title = os.environ.get("OPENROUTER_APP_NAME", "EMR Leitor de Slides e PDF")
    if referer:
        default_headers["HTTP-Referer"] = referer
    if title:
        default_headers["X-Title"] = title

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers=default_headers or None,
    )

    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 3000,
    }

    transient = 0   # erros transitórios (rate limit / API) — máx. 3
    strips = 0      # parâmetros removidos por incompatibilidade — máx. 4

    while True:
        try:
            response = client.chat.completions.create(**params)
            if not response.choices:
                # OpenRouter devolve 200 com 'error' no corpo em algumas falhas de upstream
                erro = getattr(response, "error", None)
                raise RuntimeError(f"OpenRouter não retornou resposta: {erro or response}")
            return response.choices[0].message.content or ""
        except BadRequestError as e:
            param = _param_rejeitado(e)
            # Só remove parâmetros opcionais — nunca model/messages
            if param and param in params and param not in ("model", "messages") and strips < 4:
                strips += 1
                params.pop(param, None)
                logger(f"Modelo {model} não aceita '{param}'. Removendo e tentando novamente.")
                continue
            raise RuntimeError(f"OpenRouter rejeitou a requisição (400): {e}")
        except RateLimitError:
            transient += 1
            if transient >= 3:
                raise RuntimeError("OpenRouter: rate limit persistente após 3 tentativas.")
            wait = transient * 20
            logger(f"Rate limit do OpenRouter. Aguardando {wait}s...")
            time.sleep(wait)
        except APIError as e:
            transient += 1
            if transient >= 3:
                raise RuntimeError(f"OpenRouter falhou após 3 tentativas: {e}")
            logger(f"Erro da API OpenRouter (tentativa {transient}). Tentando novamente...")
            time.sleep(5)
