"""Read-only voting progress, derived from the same durable gates as inference."""

from __future__ import annotations

import json
import math
import tier_balance
from dataclasses import dataclass
from datetime import datetime, timezone

from tier_analysis import DAILY_CALLS, DAILY_TOKENS, MAX_OUTPUT, SYSTEM


@dataclass(frozen=True)
class PollProgress:
    stage: str
    next_analysis_at: int | None = None
    closes_at: int | None = None
    last_result: str = ""


def _budget_paused(store, now):
    try:
        budget = json.loads(store.get("budget") or "{}")
        if not isinstance(budget, dict):
            return True
        day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        if budget.get("day") != day:
            return False
        calls, tokens = budget.get("calls", 0), budget.get("tokens", 0)
        if any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in (calls, tokens)
        ):
            return True
        return (
            calls >= DAILY_CALLS
            or tokens + len(SYSTEM.encode()) + MAX_OUTPUT > DAILY_TOKENS
            or store.get("analysis_status") == "quota"
        )
    except (TypeError, ValueError):
        return True


def poll_progress(
    store, *, ai_enabled=None, analyzing=False, preparing=False, maintenance=False
):
    now = store.clock()
    last_result = store.get("analysis_status") or "waiting"
    enabled = ai_enabled if ai_enabled is not None else last_result != "not-connected"
    proposal = store.active_proposal()
    if tier_balance.paused(store):
        return PollProgress("game-update")
    if proposal and proposal["status"] == "queued":
        return PollProgress("queued")
    if not proposal and analyzing:
        return PollProgress("analyzing")
    paused = not enabled or maintenance or _budget_paused(store, now)
    next_at = None if paused else math.ceil(store.next_analysis_at())
    if proposal:
        stage = "open" if now < proposal["closes_at"] else "closing"
        return PollProgress(stage, next_at, math.ceil(proposal["closes_at"]))
    if paused:
        return PollProgress("paused")
    if preparing:
        return PollProgress("preparing", next_at)
    if next_at > now:
        return PollProgress("cooldown", next_at, last_result=last_result)
    stage = "ready" if store.has_pending_comments() else "waiting-reports"
    return PollProgress(stage, last_result=last_result)


def progress_text(progress):
    if progress.stage == "game-update":
        return "**Análise:** pausada para conferir as mudanças da atualização do jogo.\n**Classificação:** posições anteriores preservadas; novas enquetes voltam após a conferência das fontes."
    if progress.stage == "queued":
        return "**Próxima enquete:** proposta pronta; preparando a publicação."
    if progress.stage in ("open", "closing"):
        current = (
            f"encerra <t:{progress.closes_at}:R>."
            if progress.stage == "open"
            else "prazo encerrado; apurando o resultado."
        )
        following = (
            f"disponível <t:{progress.next_analysis_at}:R>; uma nova enquete depende de outra proposta."
            if progress.next_analysis_at
            else "temporariamente pausada; a votação atual será concluída."
        )
        return f"**Enquete atual:** {current}\n**Nova análise:** {following}"
    if progress.stage == "analyzing":
        return "**Análise:** avaliando os relatos agora.\n**Próxima enquete:** depende do resultado desta análise."
    if progress.stage == "paused":
        return "**Análise:** temporariamente pausada; posições preservadas.\n**Próxima enquete:** nenhuma nova publicação confirmada."
    if progress.stage == "preparing":
        return "**Análise:** organizando os relatos para avaliação.\n**Próxima enquete:** ainda não confirmada."
    if progress.stage == "cooldown":
        result = (
            "A última análise não gerou proposta."
            if progress.last_result == "no-proposal"
            else "Ainda não confirmada."
        )
        if progress.last_result == "retry":
            result = "A última tentativa não foi concluída; posições preservadas."
        return f"**Próxima enquete:** {result}\n**Nova análise:** disponível <t:{progress.next_analysis_at}:R>, se houver relatos."
    if progress.stage == "ready":
        return "**Análise:** há relatos aguardando avaliação; pode começar agora.\n**Próxima enquete:** depende de uma proposta fundamentada."
    return "**Análise:** Aguardando relatos relevantes sobre o jogo.\n**Próxima enquete:** nenhuma proposta pronta."
