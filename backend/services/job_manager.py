"""
Gerenciador de Jobs em memória.
Cada job tem um ID único, status, fila de logs (para WebSocket) e resultado.
"""
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    status: str = "pending"   # pending | running | done | error
    logs: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    log_queue: asyncio.Queue = field(default_factory=asyncio.Queue)


# Dicionário global de jobs (em produção, use Redis ou banco)
_jobs: dict[str, Job] = {}


def create_job() -> Job:
    job = Job(id=str(uuid.uuid4()))
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def make_logger(job: Job):
    """Retorna uma função de log que escreve no job e na fila WebSocket."""
    def log(msg: str, level: str = "INFO"):
        entry = f"[{level}] {msg}"
        job.logs.append(entry)
        # put_nowait para não bloquear threads síncronas
        try:
            job.log_queue.put_nowait(entry)
        except Exception:
            pass
        print(entry)
    return log
