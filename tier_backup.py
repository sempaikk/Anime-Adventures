"""Verified SQLite plus immutable media snapshots; explicit, offline restoration."""

from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing
from storage_maintenance import snapshot_database, verify_database, MIN_FREE_BYTES
from tier_store import REQUIRED_TABLES
from tier_media import MEDIA_TABLES


def acquire_lease(directory):
    directory = Path(directory)
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / "tierlist.lock").open("a+")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        raise RuntimeError(
            "Já existe uma instância usando este estado. Pare o bot antes de iniciar outra ou restaurar o backup."
        )
    return stream


def verify_snapshot(directory):
    directory = Path(directory).resolve()
    database = directory / "tierlist.sqlite3"
    if database.is_symlink():
        raise ValueError("O banco do backup não pode ser um link simbólico.")
    verify_database(database, required_tables=REQUIRED_TABLES | MEDIA_TABLES)
    manifest = directory / "manifest.json"
    if manifest.is_symlink() or manifest.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Manifesto fora dos limites.")
    data = json.loads(manifest.read_text())
    if (
        data.get("schema") != 1
        or not isinstance(data.get("assets"), list)
        or len(data["assets"]) > 5000
    ):
        raise ValueError("Manifesto de backup inválido.")
    if data.get("database_sha256") != hashlib.sha256(database.read_bytes()).hexdigest():
        raise ValueError("O banco não corresponde ao hash registrado no backup.")
    with closing(sqlite3.connect(database)) as db:
        expected = {
            r[0]: r[1] for r in db.execute("SELECT digest,bytes FROM tier_media_assets")
        }
    assets = {item["digest"]: item["bytes"] for item in data["assets"]}
    if expected != assets:
        raise ValueError("O manifesto não corresponde ao banco.")
    for digest, size in assets.items():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or not isinstance(size, int)
            or not 0 < size <= 4 * 1024 * 1024
        ):
            raise ValueError("Arquivo inválido no manifesto.")
        path = directory / "media" / (digest + ".png")
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(directory)
            or not path.is_file()
            or path.stat().st_size != size
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Uma imagem do backup está ausente ou corrompida.")
    return data


def make_snapshot(database, *, now=None):
    database = Path(database)
    now = time.time() if now is None else now
    root = database.parent / "backups"
    root.mkdir(exist_ok=True)
    pointer = root / "latest.json"
    if pointer.exists():
        try:
            info = json.loads(pointer.read_text())
            if now - info["created_at"] < 86400:
                directory = root / info["directory"]
                if directory.parent == root and directory.is_dir():
                    verify_snapshot(directory)
                    return directory, "fresh"
        except (ValueError, KeyError, TypeError, OSError, sqlite3.DatabaseError):
            pass
    temporary = Path(tempfile.mkdtemp(prefix=".tierlist-", dir=root))
    try:
        snapshot_database(
            database,
            temporary / "tierlist.sqlite3",
            required_tables=REQUIRED_TABLES | MEDIA_TABLES,
        )
        with closing(sqlite3.connect(temporary / "tierlist.sqlite3")) as db:
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='global_messages'"
            ).fetchone():
                # Local snapshots preserve consent and receipts, not a historical
                # copy of the chat's short-lived text/media download URLs.
                db.execute("PRAGMA secure_delete=ON")
                db.execute("UPDATE global_messages SET payload='{}'")
                db.commit()
            assets = [
                {"digest": r[0], "bytes": r[1]}
                for r in db.execute("SELECT digest,bytes FROM tier_media_assets")
            ]
        (temporary / "media").mkdir()
        for item in assets:
            digest = item["digest"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Referência de mídia inválida.")
            source = database.parent / "media" / (digest + ".png")
            target = temporary / "media" / source.name
            try:
                os.link(source, target)
            except OSError:
                if shutil.disk_usage(root).free < item["bytes"] + MIN_FREE_BYTES:
                    raise OSError("Espaço insuficiente para backup de mídia.")
                shutil.copyfile(source, target)
        (temporary / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "created_at": now,
                    "assets": assets,
                    "database_sha256": hashlib.sha256(
                        (temporary / "tierlist.sqlite3").read_bytes()
                    ).hexdigest(),
                }
            )
        )
        verify_snapshot(temporary)
        final = root / ("tierlist-" + str(int(now)))
        if final.exists():
            final = root / (final.name + "-" + os.urandom(3).hex())
        temporary.rename(final)
        temp_pointer = pointer.with_suffix(".tmp")
        temp_pointer.write_text(
            json.dumps({"directory": final.name, "created_at": now})
        )
        temp_pointer.replace(pointer)
        # Keep the current generation and one predecessor; immutable files share inodes where possible.
        snapshots = sorted(
            (p for p in root.glob("tierlist-*") if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in snapshots[2:]:
            shutil.rmtree(old)
        return final, "created"
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def maintain_tier_storage(database):
    directory, state = make_snapshot(database)
    usage = shutil.disk_usage(Path(database).parent)
    return {
        "database_bytes": Path(database).stat().st_size,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "backup": state,
        "backup_bytes": sum(
            p.stat().st_size for p in directory.rglob("*") if p.is_file()
        ),
        "backup_modified": directory.stat().st_mtime,
    }


def restore_snapshot(snapshot, destination, *, replace=False):
    snapshot, destination = Path(snapshot).resolve(), Path(destination).resolve()
    data = verify_snapshot(snapshot)
    destination.mkdir(parents=True, exist_ok=True)
    with acquire_lease(destination):
        target = destination / "tierlist.sqlite3"
        if target.exists() and not replace:
            raise ValueError("O banco existe. Use --replace somente com o bot parado.")
        if (
            shutil.disk_usage(destination).free
            < (snapshot / "tierlist.sqlite3").stat().st_size
            + sum(a["bytes"] for a in data["assets"])
            + MIN_FREE_BYTES
        ):
            raise OSError(
                "Espaço insuficiente para restaurar sem arriscar o estado atual."
            )
        media = destination / "media"
        media.mkdir(exist_ok=True)
        for item in data["assets"]:
            name = item["digest"] + ".png"
            source = snapshot / "media" / name
            candidate = media / (name + ".restore")
            shutil.copyfile(source, candidate)
            candidate.replace(media / name)
        descriptor, name = tempfile.mkstemp(
            prefix=".tierlist-restore-", dir=destination
        )
        os.close(descriptor)
        candidate = Path(name)
        try:
            shutil.copyfile(snapshot / "tierlist.sqlite3", candidate)
            with closing(sqlite3.connect(candidate)) as db:
                db.execute("UPDATE tier_threads SET panel_hash='',index_hash=''")
                db.commit()
            verify_database(candidate, required_tables=REQUIRED_TABLES | MEDIA_TABLES)
            if target.exists():
                previous = destination / "pre-restore.sqlite3"
                snapshot_database(
                    target, previous, required_tables=REQUIRED_TABLES | MEDIA_TABLES
                )
            candidate.replace(target)
        finally:
            candidate.unlink(missing_ok=True)
    return target
