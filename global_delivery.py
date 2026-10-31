"""Publication stages for the existing relay, separate from ingestion and scheduling."""
from dataclasses import dataclass
import json
import discord
from global_store import fingerprint
from feed_contracts import classify_failure, Failure

@dataclass
class DeliveryContext:
    job: dict
    row: dict
    hook: object
    target: object
    original: object
    data: dict
    parts: list
    receipts: list

class GlobalDelivery:
    async def publish_parts(self, context):
        from global_relay import REQUIRED
        job,row,hook,target,original,data,parts,receipts = (context.job,context.row,context.hook,context.target,
            context.original,context.data,context.parts,context.receipts)
        for index, part in enumerate(parts):
            current = self.store.message(row["id"])
            if current["deleted"] or current["revision"] != row["revision"]:
                return
            active = self.store.source(job["channel_id"])
            delivery = self.store.delivery(job["source_id"], job["channel_id"])
            if (
                self.store.network_paused()
                or not active
                or active["hook_id"] != job["hook_id"]
                or delivery["state"] == "cancelled"
                or delivery["suppressed"]
                or not self.store.source(row["channel_id"])
                or not self.suitable(original.channel)
                or target.is_nsfw()
                or not self.store.consented(row["user_id"])
                or self.store.blocked(
                    row["user_id"], job["guild_id"], row["guild_id"]
                )
            ):
                return
            if not all(
                getattr(target.permissions_for(target.guild.me), flag, False)
                for flag in REQUIRED
            ):
                raise ValueError(
                    "An administrator needs to check the bot's permissions in this channel."
                )
            files, _ = self.media.files(part["files"], target.guild.filesize_limit)
            existing = receipts[index] if index < len(receipts) else None
            try:
                if existing:
                    try:
                        await hook.edit_message(
                            int(existing),
                            content=part["content"],
                            attachments=files,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    except discord.NotFound:
                        # A removed copy is a moderation decision, never resurrect it.
                        self.store.suppress(
                            job["guild_id"], job["channel_id"], existing
                        )
                        return
                    if index==0:
                        with self.store.db:
                            self.store.db.execute('UPDATE global_deliveries SET quote_hash=?,quote_dirty=0 WHERE source_id=? AND channel_id=?',(part['quote_hash'],row['id'],job['channel_id']))
                else:
                    if not await self.publish_new(context,index,part,files):
                        return False
            finally:
                for file in files:
                    file.close()
        return True

    async def publish_new(self, context, index, part, files):
        job,row,hook,data,receipts = context.job,context.row,context.hook,context.data,context.receipts
        attempt = {
            "fingerprint": fingerprint(
                {
                    "content": part["content"],
                    "username": data["username"],
                    "files": [
                        {"filename": a["filename"], "size": a["size"]}
                        for a in part["files"]
                    ],
                }
            )
        }
        with self.store.db:
            if index==0:
                self.store.db.execute('UPDATE global_deliveries SET quote_hash=? WHERE source_id=? AND channel_id=?',(part['quote_hash'],row['id'],job['channel_id']))
            self.store.db.execute(
                "UPDATE global_deliveries SET state='sending',uncertain=?,attempted=?,attempt_payload=? WHERE source_id=? AND channel_id=?",
                (
                    index,
                    self.store.clock(),
                    json.dumps(attempt),
                    row["id"],
                    job["channel_id"],
                ),
            )
        try:
            sent = await hook.send(
                part["content"] or None,
                username=data["username"],
                **(
                    {"avatar_url": data["avatar"]}
                    if data.get("avatar")
                    else {}
                ),
                files=files,
                allowed_mentions=discord.AllowedMentions.none(),
                wait=True,
            )
        except Exception as error:
            failure = classify_failure(error, posting=True)
            if failure == Failure.PERMANENT:
                raise
            self.store.retry(
                job,
                'Discord did not confirm publication.',
                uncertain=index if failure == Failure.UNCERTAIN else -1,
            )
            return
        if not sent or not getattr(sent, "id", None):
            self.store.retry(
                job,
                'Discord did not confirm publication.',
                uncertain=index,
            )
            return
        self.store.save_receipt(job, index, sent.id)
        while len(receipts) <= index:
            receipts.append(None)
        receipts[index] = str(sent.id)
        return True
