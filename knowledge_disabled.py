"""Retired /ask: no archive, AI, PC connection, source collection or public routes."""


class DisabledKnowledge:
    disabled = True
    paused = False
    reader_status = 'disabled'

    def __init__(self, bot): self.bot = bot
    def get_meta(self, key): return None
    def ensure_wiki(self): pass
    def ingest(self, event): return False
    def checkpoint(self, event): pass
    def prune(self): pass
    def backup(self): pass
    def close(self): pass
    def statistics(self):
        return {'disabled':True,'messages':0,'bytes':0,'used_bytes':0,'limit':0,'paused':False,'days':[]}
