"""Deterministic flood containment; no paid classifier or permanent automatic bans."""

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit

RULES = """## Regras da conversa
Respeite as pessoas. Não compartilhe golpes, assédio, ameaças, conteúdo sexual,
dados pessoais de terceiros ou divulgação em massa. Use Denunciar quando necessário.
Links comuns e convites ocasionais são permitidos. Links disfarçados, excesso de
menções, repetição coordenada e rajadas podem impedir o compartilhamento.
A proteção pode conter temporariamente um servidor por dez minutos, com revisão
do dono. Ela não aplica banimento permanente nem substitui a moderação humana."""


def domain(value):
    try:
        return (urlsplit(value).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""


def check_links(text):
    text = re.sub(r"```[\s\S]*?```|`[^`\n]*`", "", text)
    for shown, target in re.findall(r"\[([^\]\n]{1,500})\]\(([^\s)]{1,1000})\)", text):
        target = target.strip("<>")
        if target.casefold().startswith(("javascript:", "data:", "file:")):
            raise ValueError(
                "Esse link usa um formato inseguro. Envie o endereço HTTPS real, sem disfarçar o destino."
            )
        display = domain(shown.strip("<>"))
        actual = domain(target)
        if (
            display
            and actual
            and display.removeprefix("www.") != actual.removeprefix("www.")
        ):
            raise ValueError(
                "O endereço mostrado no link é diferente do destino. Compartilhe o link real para que todos possam conferir."
            )
    if len(re.findall(r"<@!?\d+>|<@&\d+>|@everyone|@here", text)) > 10:
        raise ValueError(
            "Reduza as menções antes de compartilhar. As cópias não notificam pessoas ou cargos."
        )


class GlobalGuard:
    def __init__(self, store):
        self.store = store

    def check(self, message, data, *, new):
        check_links(message.content or "")
        if sum(int(a.get("size") or 0) for a in data["files"]) > 128 * 1024 * 1024:
            raise ValueError(
                "Os anexos dessa mensagem ultrapassam 128 MiB de preparo temporário. Envie em partes menores; a original foi preservada."
            )
        if not new:
            return
        now = self.store.clock()
        text = unicodedata.normalize("NFKC", message.content or "").casefold()
        text = " ".join(re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text).split())
        digest = hashlib.sha256(text.encode()).hexdigest() if len(text) >= 12 else ""
        invite = int(
            bool(re.search(r"(?:discord\.gg/|discord(?:app)?\.com/invite/)", text))
        )
        with self.store.db:
            self.store.db.execute(
                "INSERT OR IGNORE INTO global_traffic VALUES(?,?,?,?,?,?)",
                (
                    str(message.id) + ":" + data["fingerprint"][:24],
                    str(message.guild.id),
                    str(message.author.id),
                    digest,
                    invite,
                    now,
                ),
            )
        counts = self.store.one(
            "SELECT COUNT(*) AS n,COALESCE(SUM(invite),0) AS invites FROM global_traffic WHERE guild_id=? AND created>?",
            (str(message.guild.id), now - 60),
        )
        peers = self.store.one(
            "SELECT COUNT(DISTINCT user_id) AS n FROM global_traffic WHERE guild_id=? AND hash=? AND hash<>'' AND created>?",
            (str(message.guild.id), digest, now - 60),
        )["n"]
        reason = ""
        if counts["n"] > 120:
            reason = "Rajada acima de 120 mensagens por minuto na origem."
        elif peers >= 8:
            reason = "Oito contas repetiram a mesma mensagem em menos de um minuto."
        elif counts["invites"] > 12:
            reason = "Mais de doze convites compartilhados por minuto na origem."
        if reason:
            self.store.restrict(
                "*", "guild", message.guild.id, 600, "automatic", reason
            )
            raise ValueError(
                "O compartilhamento deste servidor foi contido por dez minutos após uma rajada de mensagens. A conversa local continua disponível; o responsável pelo bot pode revisar a proteção."
            )
