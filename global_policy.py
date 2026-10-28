"""Deterministic flood containment; no paid classifier or permanent automatic bans."""

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit

RULES = "## Chat rules\nRespect other participants. Do not share scams, harassment, threats, sexual content,\nother people's personal information or mass advertising. Use Report when necessary.\nNormal links and occasional invitations are allowed. Disguised destinations,\nexcessive mentions, coordinated repetition and message bursts can prevent sharing.\nProtection may temporarily restrict a server for ten minutes, subject to owner review.\nIt does not apply permanent bans or replace human moderation."


def domain(value):
    try:
        value = ''.join(c for c in unicodedata.normalize('NFKC', value.strip())
                        if unicodedata.category(c) != 'Cf')
        if '://' not in value and re.fullmatch(r'(?:[\w-]+\.)+[\w-]{2,63}(?::\d+)?(?:/[^\s]*)?', value):
            value = 'https://' + value
        host = (urlsplit(value).hostname or "").casefold().rstrip(".")
        return host.encode('idna').decode('ascii')
    except (ValueError, UnicodeError):
        return ""


def check_links(text):
    text = re.sub(r"```[\s\S]*?```|`[^`\n]*`", "", text)
    for shown, target in re.findall(r"\[([^\]\n]{1,500})\]\(([^\s)]{1,1000})\)", text):
        target = target.strip("<>")
        if target.casefold().startswith(("javascript:", "data:", "file:")):
            raise ValueError(
                'This link uses an unsafe format. Send the actual HTTPS address without disguising its destination.'
            )
        display = domain(shown.strip("<>"))
        actual = domain(target)
        if (
            display
            and actual
            and display.removeprefix("www.") != actual.removeprefix("www.")
        ):
            raise ValueError(
                'The displayed address differs from the destination. Share the actual link so everyone can check it.'
            )
    if len(re.findall(r"<@!?\d+>|<@&\d+>|@everyone|@here", text)) > 10:
        raise ValueError(
            'Reduce mentions before sharing. Copies do not notify users or roles.'
        )


class GlobalGuard:
    def __init__(self, store):
        self.store = store

    def check(self, message, data, *, new):
        check_links(message.content or "")
        if sum(int(a.get("size") or 0) for a in data["files"]) > 128 * 1024 * 1024:
            raise ValueError(
                "This message's attachments exceed the 128 MiB preparation limit. Send smaller groups; the original was preserved."
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
        actor_events=self.store.one('SELECT count(*) n FROM global_traffic WHERE guild_id=? AND user_id=? AND created>?',
            (str(message.guild.id),str(message.author.id),now-60))['n']
        if counts['n']>120 and actor_events>60:
            self.store.restrict('*','user',message.author.id,300,'automatic','Repeated high-volume sharing attempts by one account.')
            raise ValueError('Your sharing is restricted for five minutes after repeated bursts. Other members can continue talking.')
        if peers >= 8 and (invite or re.search(r'https?://',text) or counts['n']>=16):
            reason = 'Coordinated repetition across accounts exceeded the temporary sharing limit.'
        elif counts["invites"] > 12:
            reason = 'The source exceeded twelve shared invitations per minute.'
        if reason:
            self.store.restrict(
                "*", "guild", message.guild.id, 600, "automatic", reason
            )
            raise ValueError(
                'Sharing from this server was restricted for ten minutes after a message burst. Local conversation remains available; the bot owner can review the restriction.'
            )
        if counts['n']>120:
            raise ValueError('This source is busy. Wait briefly before sharing another message; the original stays local. No permanent restriction was applied.')
