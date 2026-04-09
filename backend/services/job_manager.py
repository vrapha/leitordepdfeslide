"""
Gerenciador de Jobs em memória.
Cada job tem um ID único, status, fila de logs (para WebSocket) e resultado.
Jobs expiram automaticamente após 24h.
"""
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

JOB_TTL_HOURS = 24


@dataclass
class Job:
    id: str
    status: str = "pending"   # pending | running | done | error
    logs: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    log_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=JOB_TTL_HOURS)
    )


# Dicionário global de jobs (em produção, use Redis ou banco)
_jobs: dict[str, Job] = {}


def create_job() -> Job:
    _cleanup_expired()
    job = Job(id=str(uuid.uuid4()))
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    job = _jobs.get(job_id)
    if job is None:
        return None
    if datetime.now(timezone.utc) > job.expires_at:
        del _jobs[job_id]
        return None
    return job


def make_logger(job: Job):
    """Retorna uma função de log que escreve no job e na fila WebSocket."""
    def log(msg: str, level: str = "INFO"):
        entry = f"[{level}] {msg}"
        job.logs.append(entry)
        try:
            job.log_queue.put_nowait(entry)
        except Exception:
            pass
        print(entry)
    return log


def _cleanup_expired() -> None:
    """Remove jobs expirados. Chamado a cada create_job."""
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _jobs.items() if now > v.expires_at]
    for k in expired:
        del _jobs[k]
