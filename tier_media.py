"""Validated, immutable community portraits with owner review and rollback."""

from __future__ import annotations

import hashlib
import io
import warnings
import shutil
from collections import deque

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 4 * 1024 * 1024
MAX_PIXELS = 4_000_000
MAX_STORAGE = 80 * 1024 * 1024
MEDIA_TABLES = {"tier_media_assets", "tier_media_suggestions", "tier_media_active"}


def prepare(blob, *, proof=False, remove_background=False):
    if not blob or len(blob) > MAX_UPLOAD:
        raise ValueError("Envie uma imagem PNG, JPG ou WebP de até 4 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(blob)) as source:
                if (
                    source.format not in ("PNG", "JPEG", "WEBP")
                    or getattr(source, "n_frames", 1) != 1
                ):
                    raise ValueError("Use PNG, JPG ou WebP estático, sem animação.")
                width, height = source.size
                if (
                    min(width, height) < 64
                    or max(width, height) > 4096
                    or width * height > MAX_PIXELS
                ):
                    raise ValueError(
                        "A imagem precisa ter pelo menos 64 px em cada lado e no máximo 4 milhões de pixels."
                    )
                if max(width, height) / min(width, height) > (8 if proof else 4):
                    raise ValueError("Envie um recorte mais próximo do personagem.")
                source.verify()
            with Image.open(io.BytesIO(blob)) as source:
                # Convert into a fresh canvas: source EXIF, comments and ancillary data are not retained.
                converted = ImageOps.exif_transpose(source).convert("RGBA")
                image = Image.new("RGBA", converted.size)
                image.paste(converted)
                image.thumbnail(
                    (1600, 1600) if proof else (512, 512), Image.Resampling.LANCZOS
                )
                if remove_background and not proof:
                    image = remove_uniform_background(image)
                if not proof:
                    box = image.getchannel("A").getbbox()
                    if box is None:
                        raise ValueError("A imagem está totalmente transparente.")
                    image = image.crop(box)
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
                while output.tell() > MAX_UPLOAD and proof:
                    image.thumbnail(
                        (int(image.width * 0.8), int(image.height * 0.8)),
                        Image.Resampling.LANCZOS,
                    )
                    output = io.BytesIO()
                    image.save(output, format="PNG", optimize=True)
                if output.tell() > MAX_UPLOAD:
                    raise ValueError(
                        "A imagem preparada excede 4 MB. Envie um recorte menor."
                    )
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(
            "O arquivo não é uma imagem válida ou excede os limites de segurança."
        ) from exc


def remove_uniform_background(image):
    image = image.copy()
    width, height = image.size
    pixels = image.load()
    border = (
        [(x, 0) for x in range(width)]
        + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(height)]
        + [(width - 1, y) for y in range(height)]
    )
    colors = [pixels[x, y][:3] for x, y in border if pixels[x, y][3] > 0]
    if not colors:
        return image
    color = tuple(sorted(c[i] for c in colors)[len(colors) // 2] for i in range(3))

    def close(pixel):
        return max(abs(pixel[i] - color[i]) for i in range(3)) <= 12

    if sum(close(pixels[x, y]) for x, y in border) / len(border) < 0.9:
        raise ValueError(
            "O fundo não é uniforme. Preserve o original ou envie um PNG já recortado."
        )
    queue = deque((x, y) for x, y in border if close(pixels[x, y]))
    visited = set()
    while queue:
        x, y = queue.popleft()
        if (x, y) in visited or not close(pixels[x, y]):
            continue
        visited.add((x, y))
        pixels[x, y] = (*pixels[x, y][:3], 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited:
                queue.append((nx, ny))
    if len(visited) > width * height * 0.95:
        raise ValueError(
            "O recorte removeria quase toda a imagem. O original foi preservado."
        )
    return image


class MediaLibrary:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog
        self.root = store.path.parent / "media"
        self.root.mkdir(exist_ok=True)
        self._verified = {}
        self.store.connection.executescript("""
          CREATE TABLE IF NOT EXISTS tier_media_assets(
            digest TEXT PRIMARY KEY,bytes INTEGER NOT NULL,created_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_media_suggestions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,unit_id TEXT NOT NULL,user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL,appearance TEXT NOT NULL,note TEXT NOT NULL,
            original_hash TEXT NOT NULL,preview_hash TEXT NOT NULL,proof_hash TEXT,
            created_at REAL NOT NULL,status TEXT NOT NULL DEFAULT 'pending');
          CREATE TABLE IF NOT EXISTS tier_media_active(
            unit_id TEXT PRIMARY KEY,suggestion_id INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS tier_upload_attempts(
            user_id TEXT NOT NULL,guild_id TEXT NOT NULL,created_at REAL NOT NULL);
          CREATE INDEX IF NOT EXISTS tier_upload_actor_time ON tier_upload_attempts(user_id,created_at);
          CREATE INDEX IF NOT EXISTS tier_upload_guild_time ON tier_upload_attempts(guild_id,created_at);
        """)

    def path(self, digest):
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Referência de imagem inválida.")
        return self.root / (digest + ".png")

    def available(self, digest):
        """Check immutable media once per file change, with bounded reads."""
        path = self.path(digest)
        try:
            stat = path.stat()
            if (
                path.is_symlink()
                or not path.is_file()
                or not 0 < stat.st_size <= MAX_UPLOAD
            ):
                return False
            stamp = (
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            )
            if self._verified.get(digest) != stamp:
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    self._verified.pop(digest, None)
                    return False
                self._verified[digest] = stamp
            return True
        except OSError:
            self._verified.pop(digest, None)
            return False

    def put(self, blob):
        digest = hashlib.sha256(blob).hexdigest()
        path = self.path(digest)
        valid = (
            path.is_file()
            and path.stat().st_size <= MAX_UPLOAD
            and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        )
        if not valid:
            size = self.store.connection.execute(
                "SELECT COALESCE(SUM(bytes),0) FROM tier_media_assets"
            ).fetchone()[0]
            registered = self.store.connection.execute(
                "SELECT bytes FROM tier_media_assets WHERE digest=?", (digest,)
            ).fetchone()
            if size + (0 if registered else len(blob)) > MAX_STORAGE:
                raise ValueError(
                    "O armazenamento de imagens está cheio. Aguarde a revisão da fila."
                )
            if shutil.disk_usage(self.root).free < len(blob) + 16 * 1024 * 1024:
                raise ValueError(
                    "O espaço disponível está baixo. O retrato atual foi preservado."
                )
            temporary = path.with_suffix(".tmp")
            try:
                temporary.write_bytes(blob)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        self.store.connection.execute(
            "INSERT OR IGNORE INTO tier_media_assets VALUES(?,?,?)",
            (digest, len(blob), self.store.clock()),
        )
        return digest

    def suggestion(self, suggestion_id):
        rows = self.store.rows(
            "SELECT * FROM tier_media_suggestions WHERE id=?", (suggestion_id,)
        )
        return rows[0] if rows else None

    def check_submission(self, unit_id, user_id, guild_id, appearance, note):
        if unit_id not in self.catalog.units:
            raise ValueError("Informe a unidade e a forma exatas.")
        if not 15 <= len(note.strip()) <= 700 or len(appearance) > 150:
            raise ValueError(
                "Explique a correção em 15 a 700 caracteres e a skin em até 150."
            )
        db, now = self.store.connection, self.store.clock()
        if (
            db.execute(
                "SELECT COUNT(*) FROM tier_media_suggestions WHERE status='pending'"
            ).fetchone()[0]
            >= 100
        ):
            raise ValueError("A fila de imagens está cheia. Aguarde a revisão.")
        if (
            db.execute(
                "SELECT COUNT(*) FROM tier_media_suggestions WHERE user_id=? AND created_at>?",
                (str(user_id), now - 86400),
            ).fetchone()[0]
            >= 3
        ):
            raise ValueError("Você já enviou três sugestões hoje. Aguarde a revisão.")
        if (
            db.execute(
                "SELECT COUNT(*) FROM tier_media_suggestions WHERE guild_id=? AND created_at>?",
                (str(guild_id), now - 86400),
            ).fetchone()[0]
            >= 20
        ):
            raise ValueError("Este servidor atingiu o limite diário de sugestões.")

    def begin_upload(self, user_id, guild_id):
        """Reserve an attempt before network/decoding, including invalid or duplicate files."""
        now = self.store.clock()
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            self.store.connection.execute(
                "DELETE FROM tier_upload_attempts WHERE created_at<=?", (now - 600,)
            )
            for column, value, limit, label in (
                ("user_id", str(user_id), 6, "Você tentou enviar muitas imagens"),
                (
                    "guild_id",
                    str(guild_id),
                    30,
                    "Este servidor recebeu muitas tentativas de envio",
                ),
                (None, None, 1000, "A preparação de imagens está ocupada"),
            ):
                count, oldest = self.store.connection.execute(
                    "SELECT COUNT(*),MIN(created_at) FROM tier_upload_attempts"
                    + (f" WHERE {column}=?" if column else ""),
                    (value,) if column else (),
                ).fetchone()
                if count >= limit:
                    minutes = max(1, int((oldest + 600 - now + 59) // 60))
                    raise ValueError(f"{label}. Tente novamente em {minutes} min.")
            self.store.connection.execute(
                "INSERT INTO tier_upload_attempts VALUES(?,?,?)",
                (str(user_id), str(guild_id), now),
            )

    def submit(
        self,
        unit_id,
        user_id,
        guild_id,
        appearance,
        note,
        portrait,
        proof=None,
        *,
        _prepared=False,
    ):
        self.check_submission(unit_id, user_id, guild_id, appearance, note)
        db, now = self.store.connection, self.store.clock()
        # Only the modal passes bytes already normalized by prepare() in a worker.
        if not _prepared:
            portrait = prepare(portrait)
            proof = prepare(proof, proof=True) if proof else None
        fingerprint = hashlib.sha256(portrait).hexdigest()
        existing = self.path(fingerprint)
        valid_existing = (
            existing.is_file()
            and existing.stat().st_size <= MAX_UPLOAD
            and hashlib.sha256(existing.read_bytes()).hexdigest() == fingerprint
        )
        if (
            valid_existing
            and db.execute(
                "SELECT 1 FROM tier_media_suggestions WHERE unit_id=? AND original_hash=? AND status IN ('pending','approved')",
                (unit_id, fingerprint),
            ).fetchone()
        ):
            raise ValueError("Essa imagem já foi enviada para esta forma.")
        with db:
            original = self.put(portrait)
            proof_hash = self.put(proof) if proof else None
            cursor = db.execute(
                "INSERT INTO tier_media_suggestions(unit_id,user_id,guild_id,appearance,note,original_hash,preview_hash,proof_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    unit_id,
                    str(user_id),
                    str(guild_id),
                    appearance.strip(),
                    note.strip(),
                    original,
                    original,
                    proof_hash,
                    now,
                ),
            )
        return cursor.lastrowid

    def pending(self):
        rows = self.store.rows(
            "SELECT * FROM tier_media_suggestions WHERE status='pending' ORDER BY id"
        )
        return [r for r in rows if r["unit_id"] in self.catalog.units]

    def crop_background(self, suggestion_id, *, _prepared=None):
        row = self.suggestion(suggestion_id)
        if not row or row["status"] != "pending":
            raise ValueError("Essa sugestão já foi revisada.")
        with self.store.connection:
            preview = row["original_hash"]
            if row["preview_hash"] == row["original_hash"]:
                preview = self.put(
                    _prepared
                    if _prepared is not None
                    else prepare(
                        self.path(row["original_hash"]).read_bytes(),
                        remove_background=True,
                    )
                )
            self.store.connection.execute(
                "UPDATE tier_media_suggestions SET preview_hash=? WHERE id=?",
                (preview, suggestion_id),
            )

    def decide(self, suggestion_id, actor_id, *, approve):
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            row = self.suggestion(suggestion_id)
            if not row or row["status"] != "pending":
                raise ValueError("Essa sugestão já foi revisada.")
            if approve:
                if row["unit_id"] not in self.catalog.units:
                    raise ValueError(
                        "Essa forma foi retirada do catálogo ativo do jogo."
                    )
                if not self.available(row["preview_hash"]):
                    raise ValueError(
                        "A imagem está ausente ou corrompida. A atual foi preservada."
                    )
                self.store.connection.execute(
                    "INSERT OR REPLACE INTO tier_media_active VALUES(?,?)",
                    (row["unit_id"], suggestion_id),
                )
                self._bump()
                self.store.audit(
                    "portrait-approved",
                    actor_id,
                    "Retrato atualizado: "
                    + self.catalog.units[row["unit_id"]].name
                    + (". Skin: " + row["appearance"] if row["appearance"] else "")
                    + ". As posições foram preservadas.",
                )
            self.store.connection.execute(
                "UPDATE tier_media_suggestions SET status=? WHERE id=?",
                ("approved" if approve else "rejected", suggestion_id),
            )

    def _bump(self):
        self.store.connection.execute(
            "INSERT INTO tier_meta VALUES('media_revision','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1"
        )

    def undo(self, unit_id, expected_suggestion, actor_id):
        if unit_id not in self.catalog.units:
            raise ValueError("Essa forma foi retirada do catálogo ativo do jogo.")
        with self.store.connection:
            self.store.connection.execute("BEGIN IMMEDIATE")
            active = self.store.connection.execute(
                "SELECT suggestion_id FROM tier_media_active WHERE unit_id=?",
                (unit_id,),
            ).fetchone()
            if not active or active[0] != expected_suggestion:
                raise ValueError("O retrato mudou. Abra a revisão novamente.")
            previous = self.store.connection.execute(
                "SELECT id FROM tier_media_suggestions WHERE unit_id=? AND status='approved' AND id<? ORDER BY id DESC LIMIT 1",
                (unit_id, expected_suggestion),
            ).fetchone()
            if previous and not self.available(
                self.suggestion(previous[0])["preview_hash"]
            ):
                raise ValueError(
                    "O retrato anterior está ausente ou corrompido. A imagem atual foi preservada."
                )
            self.store.connection.execute(
                "UPDATE tier_media_suggestions SET status='reverted' WHERE id=?",
                (expected_suggestion,),
            )
            if previous:
                self.store.connection.execute(
                    "UPDATE tier_media_active SET suggestion_id=? WHERE unit_id=?",
                    (previous[0], unit_id),
                )
            else:
                self.store.connection.execute(
                    "DELETE FROM tier_media_active WHERE unit_id=?", (unit_id,)
                )
            self._bump()
            self.store.audit(
                "portrait-reverted",
                actor_id,
                "Retrato anterior restaurado: "
                + self.catalog.units[unit_id].name
                + ". As posições foram preservadas.",
            )

    def approved(self):
        rows = self.store.rows(
            "SELECT a.unit_id,s.* FROM tier_media_active a JOIN tier_media_suggestions s ON s.id=a.suggestion_id"
        )
        result = {}
        for row in rows:
            path = self.path(row["preview_hash"])
            if row["unit_id"] in self.catalog.units and self.available(
                row["preview_hash"]
            ):
                result[row["unit_id"]] = {
                    "absolute_path": str(path),
                    "path": str(path),
                    "suggestion_id": row["id"],
                }
        return result

    def cleanup(self):
        self._verified.clear()
        with self.store.connection:
            self.store.connection.execute(
                "DELETE FROM tier_upload_attempts WHERE created_at<=?",
                (self.store.clock() - 600,),
            )
            self.store.connection.execute(
                "UPDATE tier_media_suggestions SET status='expired' WHERE status='pending' AND created_at<?",
                (self.store.clock() - 7 * 86400,),
            )
            # Preserve active and the two most recent approved predecessors for each unit.
            self.store.connection.execute(
                "DELETE FROM tier_media_suggestions WHERE created_at<? AND id NOT IN (SELECT suggestion_id FROM tier_media_active) AND id NOT IN (SELECT id FROM (SELECT id,ROW_NUMBER() OVER(PARTITION BY unit_id ORDER BY id DESC) n FROM tier_media_suggestions WHERE status='approved') WHERE n<=3)",
                (self.store.clock() - 30 * 86400,),
            )
            used = {
                v
                for row in self.store.rows(
                    "SELECT original_hash,preview_hash,proof_hash FROM tier_media_suggestions"
                )
                for v in row.values()
                if v
            }
            for row in self.store.rows("SELECT digest FROM tier_media_assets"):
                if row["digest"] not in used:
                    self.path(row["digest"]).unlink(missing_ok=True)
                    self.store.connection.execute(
                        "DELETE FROM tier_media_assets WHERE digest=?", (row["digest"],)
                    )
        # A crash between writing a file and committing its row leaves a harmless orphan.
        registered = {
            r["digest"] for r in self.store.rows("SELECT digest FROM tier_media_assets")
        }
        for path in self.root.glob("*.png"):
            if (
                path.stem not in registered
                and path.stat().st_mtime < self.store.clock() - 86400
            ):
                path.unlink(missing_ok=True)

    def manifest(self):
        return {
            "schema": 1,
            "assets": [
                dict(r) for r in self.store.rows("SELECT * FROM tier_media_assets")
            ],
        }
