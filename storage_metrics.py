"""Small aggregate capacity measurements; no conversation content or credentials."""


def storage_metrics(store):
    db=store.db
    page=db.execute('PRAGMA page_size').fetchone()[0]
    allocated=db.execute('PRAGMA page_count').fetchone()[0]*page
    reusable=db.execute('PRAGMA freelist_count').fetchone()[0]*page
    active=store.one('SELECT count(*) n FROM global_channels WHERE active=1')['n']
    daily=store.one('SELECT count(*) n FROM global_messages WHERE created>?',(store.clock()-86400,))['n']
    copies=store.one('SELECT count(*) n FROM global_deliveries')['n']
    expired=store.one('SELECT count(*) n FROM global_messages WHERE expires<?',(store.clock(),))['n']
    return {'allocated':allocated,'reusable':reusable,'active_servers':active,'daily_sources':daily,
            'estimated_daily_copies':daily*max(0,active-1),'stored_copies':copies,'expired_sources':expired}
