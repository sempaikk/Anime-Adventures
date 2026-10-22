"""Explicit game-update boundaries; preserve rankings and previous community votes."""

import json
import math
import secrets


def state(store):
    return json.loads(store.get("game_update") or "{}")


def revision(store):
    return state(store).get("revision", "")


def paused(store):
    return bool(state(store).get("paused"))


def cutoff(store):
    return state(store).get("effective_at", 0)


def decision_cutoff(store):
    return state(store).get("registered_at", 0)


def previous_proposal(store):
    return state(store).get("previous_proposal", 0)


def register(store, *, expected, label, effective_at, reason, actor):
    label, reason = label.strip(), reason.strip()
    if not 2 <= len(label) <= 80 or not 20 <= len(reason) <= 500:
        raise ValueError(
            "Informe o nome da atualização e um motivo com 20 a 500 caracteres."
        )
    if (
        type(effective_at) not in (int, float)
        or not math.isfinite(effective_at)
        or not 0 < effective_at <= store.clock()
    ):
        raise ValueError(
            "Informe uma data válida em que a atualização já entrou no jogo."
        )
    with store.connection:
        store.connection.execute("BEGIN IMMEDIATE")
        old = state(store)
        if expected != old.get("revision", ""):
            raise ValueError(
                "A atualização registrada mudou. Abra os controles novamente."
            )
        if effective_at < old.get("effective_at", 0):
            raise ValueError(
                "A data não pode ser anterior à atualização já registrada."
            )
        entry = {
            "revision": secrets.token_hex(12),
            "label": label,
            "effective_at": effective_at,
            "registered_at": store.clock(),
            "paused": True,
            "previous_proposal": store.connection.execute(
                "SELECT COALESCE(MAX(id),0) FROM tier_proposals"
            ).fetchone()[0],
        }
        for row in store.rows(
            "SELECT id FROM tier_proposals WHERE status IN ('open','queued')"
        ):
            store.connection.execute(
                "UPDATE tier_proposals SET status='game-updated',outcome=? WHERE id=?",
                (json.dumps(store.poll_counts(row["id"])), row["id"]),
            )
        store.connection.execute(
            "INSERT OR REPLACE INTO tier_meta VALUES('game_update',?)",
            (json.dumps(entry),),
        )
        store.connection.execute(
            "UPDATE tier_meta SET value='game-update' WHERE key='analysis_status'"
        )
        store.audit("game-update", actor, label + ": " + reason)
    return entry


def resume(store, *, expected, source_version, reason, actor):
    if not isinstance(source_version, str) or not 1 <= len(source_version) <= 200:
        raise ValueError("As fontes precisam estar disponíveis antes de retomar.")
    if not 20 <= len(reason.strip()) <= 500:
        raise ValueError("Explique a conferência das fontes em 20 a 500 caracteres.")
    with store.connection:
        store.connection.execute("BEGIN IMMEDIATE")
        entry = state(store)
        if not entry.get("paused") or expected != entry.get("revision"):
            raise ValueError("O estado mudou. Abra os controles novamente.")
        entry.update(paused=False, reviewed_source_version=source_version)
        store.connection.execute(
            "INSERT OR REPLACE INTO tier_meta VALUES('game_update',?)",
            (json.dumps(entry),),
        )
        store.connection.execute(
            "UPDATE tier_meta SET value='waiting' WHERE key='analysis_status'"
        )
        store.connection.execute(
            "UPDATE tier_meta SET value='0' WHERE key='last_attempt'"
        )
        store.audit(
            "game-update-reviewed", actor, entry["label"] + ": " + reason.strip()
        )
    return entry
