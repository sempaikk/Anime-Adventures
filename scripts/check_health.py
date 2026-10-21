"""Check a configured public readiness URL without printing its contents or credentials."""

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def check_ready(url, *, opener=urlopen):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Configure uma URL pública HTTPS, sem credenciais.')
    try:
        request=Request(url,headers={'User-Agent':'AnimeAdventuresAvailability/1.0'})
        with opener(request,timeout=10) as response:
            raw=response.read(4097)
            if response.status!=200 or len(raw)>4096:
                return False
            return json.loads(raw).get('status')=='ready'
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,AttributeError):
        return False


if __name__=='__main__':
    url=os.getenv('BOT_HEALTH_URL','')
    if not url:
        raise SystemExit('BOT_HEALTH_URL ainda não foi configurada.')
    for attempt in range(3):
        if check_ready(url):
            print('Readiness: OK')
            sys.exit(0)
        if attempt<2:
            time.sleep(5)
    raise SystemExit('Readiness indisponível após três tentativas. Confira o serviço de produção.')
