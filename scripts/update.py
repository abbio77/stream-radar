#!/usr/bin/env python3
"""Discover recent Italian streaming candidates using TMDb (not a verified provider release calendar)."""
import datetime as dt
import json
import os
import pathlib
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT=pathlib.Path(__file__).resolve().parents[1]
TOKEN=os.environ.get('TMDB_READ_ACCESS_TOKEN','').strip()
if not TOKEN:
    raise SystemExit('Missing TMDB_READ_ACCESS_TOKEN secret. Existing data.json unchanged.')
TODAY=dt.datetime.now(ZoneInfo('Europe/Rome')).date()
START=TODAY-dt.timedelta(days=3)
PROVIDERS={
    'Netflix': [8], 'Prime Video':[9,119], 'Apple TV+':[350],
    'Paramount+':[531, 1853], 'HBO Max':[1899, 384],
    'Crunchyroll':[283], 'Disney+':[337]
}

def api(path,params=None):
    url='https://api.themoviedb.org/3/'+path.lstrip('/')+'?'+urllib.parse.urlencode(params or {})
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+TOKEN,'accept':'application/json'})
    with urllib.request.urlopen(request, timeout=35) as r:
        return json.load(r)

def discover(kind, provider_ids):
    # These are *candidate titles*, not their first date added to a streaming service.
    common={'language':'it-IT','watch_region':'IT','with_watch_monetization_types':'flatrate',
            'with_watch_providers':'|'.join(map(str,provider_ids)),'sort_by':'popularity.desc'}
    if kind=='movie':
        common.update({'region':'IT','with_release_type':'4','release_date.gte':START.isoformat(),'release_date.lte':TODAY.isoformat()})
    else:
        common.update({'first_air_date.gte':START.isoformat(),'first_air_date.lte':TODAY.isoformat()})
    for page in (1,2):
        data=api('discover/'+kind,dict(common,page=page))
        for result in data.get('results',[]):
            yield result
        if page>=data.get('total_pages',1):break

def checked_provider(kind, id_, candidates):
    try:
        prov=api(f'{kind}/{id_}/watch/providers').get('results',{}).get('IT',{})
        active={p.get('provider_id') for p in prov.get('flatrate',[])}
        return bool(active.intersection(candidates)),prov.get('link')
    except Exception:return False,None

items=[]
for platform,ids in PROVIDERS.items():
    for kind in ('movie','tv'):
        try:
            candidates=list(discover(kind,ids))
        except Exception as e:
            print(f'Warning: {platform} {kind}: {e}')
            continue
        for r in candidates:
            day=r.get('release_date' if kind=='movie' else 'first_air_date')
            if not day or not (START.isoformat()<=day<=TODAY.isoformat()):continue
            available,link=checked_provider(kind,r['id'],set(ids))
            if not available:continue
            name=r.get('title') if kind=='movie' else r.get('name')
            if not name:continue
            votes=r.get('vote_count',0)
            items.append({'id':f'{platform}-{kind}-{r["id"]}','date':day,'platform':platform,'title':name,
                          'type':'film' if kind=='movie' else 'serie','kind':'Film' if kind=='movie' else 'Serie',
                          'genre':'','plot':r.get('overview') or 'Trama non disponibile in italiano.',
                          'rating':round(r['vote_average'],1) if votes>=10 else None,
                          'rating_source':'TMDb' if votes>=10 else None,
                          'poster':'https://image.tmdb.org/t/p/w342'+r['poster_path'] if r.get('poster_path') else None,
                          'audio_italiano':'unknown','audio_note':'TMDb non documenta la traccia audio italiana: verifica nella piattaforma.',
                          'access':'Segnalato in abbonamento in Italia su TMDb/JustWatch; data indicata riferita al titolo, NON confermata come data ingresso in catalogo.',
                          'link':link or f'https://www.themoviedb.org/{kind}/{r["id"]}'})
items.sort(key=lambda x:(x['date'],x['platform']),reverse=True)
old={}
path=ROOT/'data.json'
try:
    old=json.loads(path.read_text(encoding='utf8'))
except Exception:pass
# Historical archive of discovered candidates, with a 45-day retention window.
for item in old.get('items',[]):
    if item.get('date','')>=(TODAY-dt.timedelta(days=45)).isoformat() and not any(i['id']==item['id'] for i in items):
        items.append(item)
items.sort(key=lambda x:x.get('date',''),reverse=True)
out={'updated_at':dt.datetime.now(ZoneInfo('Europe/Rome')).isoformat(),'notice':'Novità potenziali: TMDb segnala titoli con data recente e streaming incluso in Italia, ma NON certifica il giorno di aggiunta al catalogo. I nuovi episodi delle serie già avviate e i doppiaggi italiani richiedono una fonte aggiuntiva.','source_note':'Metadati: TMDb. Disponibilità provider: JustWatch tramite TMDb. Non ufficialmente approvata/certificata da TMDb.','items':items[:250]}
path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print('Wrote',len(out['items']),'candidate entries')
