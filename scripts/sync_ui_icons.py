"""Explicit maintenance command: upload reviewed wiki icons to this bot application.

Run only when changing the icon library. Never called by the bot or its tests.
Existing matching names are reused. No server emoji permissions are needed.
"""

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sys

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quiz_icons import ICONS_FILE, load_icons


async def sync_icons():
    token = os.environ['DISCORD_TOKEN']
    icons = load_icons()
    async with aiohttp.ClientSession(
        trust_env=True, headers={'Authorization': 'Bot ' + token},
        timeout=aiohttp.ClientTimeout(total=25),
    ) as session:
        async def request(method, path, **kwargs):
            for attempt in range(4):
                async with session.request(method, 'https://discord.com/api/v10' + path, **kwargs) as response:
                    body = await response.json()
                    if response.status == 429 and attempt < 3:
                        delay = max(.05, float(body.get('retry_after', 1)))
                        if delay > 30:
                            raise RuntimeError('Discord requested a longer cooldown; run this command later.')
                        await asyncio.sleep(delay)
                        continue
                    if response.status >= 400:
                        raise RuntimeError(f'Discord HTTP {response.status}; request stopped.')
                    return body

        app = await request('GET', '/oauth2/applications/@me')
        endpoint = f'/applications/{app["id"]}/emojis'
        existing = {item['name']: item for item in (await request('GET', endpoint))['items']}
        document = json.loads(ICONS_FILE.read_text(encoding='utf-8'))
        for key, icon in icons.items():
            path = (ROOT / icon['upload_path']).resolve()
            if not path.is_relative_to(ROOT / 'assets/ui'):
                raise ValueError('Invalid icon path.')
            raw = path.read_bytes()
            if not raw.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(raw).hexdigest() != icon['upload_sha256']:
                raise ValueError('Icon bytes differ from the reviewed manifest.')
            item = existing.get(icon['name'])
            if not item:
                image = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
                item = await request('POST', endpoint, json={'name': icon['name'], 'image': image})
            document['icons'][key]['id'] = item['id']
            # Save each confirmed ID so an interrupted run does not create duplicate icons.
            temporary = ICONS_FILE.with_suffix('.tmp')
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(ICONS_FILE)
            print(f'{key}: registered')


if __name__ == '__main__':
    asyncio.run(sync_icons())
