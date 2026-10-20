#!/usr/bin/env python3
"""Italian streaming candidates. TMDb dates never imply an Italian catalogue premiere."""
import datetime as dt
import json
import math
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROVIDERS = {
    'Netflix': [8], 'Prime Video': [9, 119], 'Apple TV+': [350],
    'Paramount+': [531, 1853], 'HBO Max': [1899, 384],
    'Crunchyroll': [283], 'Disney+': [337],
}
RETENTION_DAYS = 45
LOOKBACK_DAYS = 14
MAX_PAGES = 20


def iso_day(value):
    try:
        return dt.date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def rating_fields(details):
    count, value = details.get('vote_count'), details.get('vote_average')
    valid = (isinstance(count, int) and count >= 10 and
             isinstance(value, (int, float)) and math.isfinite(value) and 0 < value <= 10)
    return {'rating': round(value, 1) if valid else None,
            'rating_source': 'TMDb' if valid else None,
            'rating_count': count if isinstance(count, int) and count >= 0 else 0}


def poster_url(details):
    posters = details.get('images', {}).get('posters', [])
    # Italian artwork first, then textless, English, original-language artwork.
    languages = ['it', None, 'en', details.get('original_language')]
    for lang in languages:
        matches = [p for p in posters if p.get('iso_639_1') == lang and p.get('file_path')]
        if matches:
            path = max(matches, key=lambda p: (p.get('vote_count', 0), p.get('width', 0)))['file_path']
            return 'https://image.tmdb.org/t/p/w342' + path
    path = details.get('poster_path')
    return 'https://image.tmdb.org/t/p/w342' + path if path else None


def audio_fields(item, evidence, today):
    """Use recent, reviewed, platform/region/episode-specific evidence only.

    A title being in Italy or having spoken_languages=it is NOT audio evidence.
    Evidence is editorial, not an automatic language guess; see README schema.
    """
    unknown = {'audio_italiano': 'unknown', 'audio_note':
               'Traccia italiana non confermata per questa piattaforma e questa edizione.'}
    record = evidence.get(item['id'])
    if not isinstance(record, dict):
        return unknown
    checked = iso_day(record.get('checked_at'))
    expires = iso_day(record.get('expires_at'))
    url = record.get('source_url', '')
    if not (record.get('region') == 'IT' and record.get('platform') == item['platform'] and
            checked and expires and checked <= today.isoformat() <= expires and
            (today - dt.date.fromisoformat(checked)).days <= 30 and
            record.get('status') in ('yes', 'sub') and record.get('note') and
            urllib.parse.urlparse(url).scheme == 'https' and urllib.parse.urlparse(url).hostname):
        return unknown
    if item.get('media_type') == 'tv' and (
            record.get('season') != item.get('season') or
            record.get('episode') != item.get('episode') or item.get('episode') is None):
        return unknown
    return {'audio_italiano': record['status'], 'audio_note': record['note'],
            'audio_source': url, 'audio_checked_at': checked,
            'audio_scope': record.get('scope', 'Edizione italiana sulla piattaforma indicata')}


class Client:
    def __init__(self, token):
        self.token = token
        self.cache = {}

    def api(self, path, params=None):
        query = urllib.parse.urlencode(params or {})
        url = 'https://api.themoviedb.org/3/' + path.lstrip('/') + '?' + query
        if url in self.cache:
            return self.cache[url]
        request = urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + self.token, 'accept': 'application/json'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    result = json.load(response)
                self.cache[url] = result
                return result
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                time.sleep(min(float(error.headers.get('Retry-After', 2 ** attempt)), 10))
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)

    def discover(self, kind, today):
        ids = sorted({id_ for values in PROVIDERS.values() for id_ in values})
        params = {'language': 'it-IT', 'watch_region': 'IT',
                  'with_watch_monetization_types': 'flatrate',
                  'with_watch_providers': '|'.join(map(str, ids)),
                  'include_adult': 'false', 'sort_by': 'popularity.desc'}
        start = (today - dt.timedelta(days=LOOKBACK_DAYS - 1)).isoformat()
        if kind == 'movie':
            params.update({'region': 'IT', 'with_release_type': '4',
                           'release_date.gte': start, 'release_date.lte': today.isoformat()})
        else:
            # air_date includes returning series; first_air_date misses them.
            params.update({'air_date.gte': start, 'air_date.lte': today.isoformat(),
                           'timezone': 'Europe/Rome', 'include_null_first_air_dates': 'false'})
        for page in range(1, MAX_PAGES + 1):
            data = self.api('discover/' + kind, dict(params, page=page))
            yield from data.get('results', [])
            if page >= data.get('total_pages', 1):
                return
        raise RuntimeError('Ricerca troppo ampia: limite pagine raggiunto; catalogo precedente conservato.')


def release_events(kind, details, client, today):
    start = (today - dt.timedelta(days=LOOKBACK_DAYS - 1)).isoformat()
    if kind == 'movie':
        days = {iso_day(r.get('release_date'))
                for country in details.get('release_dates', {}).get('results', [])
                if country.get('iso_3166_1') == 'IT'
                for r in country.get('release_dates', []) if r.get('type') == 4}
        return [{'date': day, 'date_basis': 'digital_it', 'date_note':
                 'Data digitale italiana TMDb; ingresso nel singolo catalogo non confermato.'}
                for day in sorted(d for d in days if d and start <= d <= today.isoformat())]
    events = []
    # Inspect every season that can contain a recent episode, excluding specials.
    for season in details.get('seasons', []):
        number, day = season.get('season_number', 0), iso_day(season.get('air_date'))
        if number <= 0 or not day or day > today.isoformat():
            continue
        # Last season and recently started seasons cover current/overlapping releases.
        if number != max((s.get('season_number', 0) for s in details.get('seasons', [])
                          if iso_day(s.get('air_date')) and s['air_date'][:10] <= today.isoformat()), default=0) and day < start:
            continue
        data = client.api(f'tv/{details["id"]}/season/{number}', {'language': 'it-IT'})
        for episode in data.get('episodes', []):
            air = iso_day(episode.get('air_date'))
            if air and start <= air <= today.isoformat():
                events.append({'date': air, 'season': number, 'episode': episode['episode_number'],
                               'episode_title': episode.get('name', ''),
                               'date_basis': 'episode_original', 'date_note':
                               'Prima messa in onda TMDb; uscita di questo episodio in Italia da verificare.'})
    return events


def build_catalog(client, old, evidence, today):
    now = dt.datetime.now(ZoneInfo('Europe/Rome')).isoformat()
    cutoff = (today - dt.timedelta(days=RETENTION_DAYS)).isoformat()
    candidates = {}
    for kind in ('movie', 'tv'):
        for result in client.discover(kind, today):
            candidates[(kind, result['id'])] = None
    history = {}
    for item in old.get('items', []):
        day = iso_day(item.get('date'))
        if not day or not cutoff <= day <= today.isoformat():
            continue
        kind, id_ = item.get('media_type'), item.get('tmdb_id')
        if not kind or not id_:
            match = re.search(r'-(movie|tv)-(\d+)(?:-|$)', item.get('id', ''))
            if not match:
                continue
            kind, id_ = match[1], int(match[2])
        if kind not in ('movie', 'tv'):
            continue
        candidates[(kind, id_)] = None
        history.setdefault((kind, id_), []).append(item)
    items, errors = {}, []
    for kind, id_ in candidates:
        try:
            details = client.api(f'{kind}/{id_}', {'language': 'it-IT',
                'append_to_response': 'watch/providers,images,release_dates',
                'include_image_language': 'it,en,null'})
            if details.get('adult'):
                continue
            provider = details.get('watch/providers', {}).get('results', {}).get('IT', {})
            active = {p['provider_id'] for p in provider.get('flatrate', [])}
            platforms = [p for p, ids in PROVIDERS.items() if active.intersection(ids)]
            if not platforms:
                continue
            recent_events = release_events(kind, details, client, today)
            events = [(event, None) for event in recent_events]
            genres = details.get('genres', [])
            genre_ids = {g['id'] for g in genres}
            category = ('documentario' if 99 in genre_ids else
                        'anime' if 16 in genre_ids and details.get('original_language') == 'ja' else
                        'film' if kind == 'movie' else 'serie')
            base = {'tmdb_id': id_, 'media_type': kind,
                    'title': details.get('title') or details.get('name'), 'type': category,
                    'genre': ' · '.join(g['name'] for g in genres),
                    'plot': details.get('overview') or 'Trama non disponibile in italiano.',
                    'poster': poster_url(details), **rating_fields(details),
                    'availability_checked_at': now,
                    'access': 'Abbonamento in Italia segnalato da JustWatch tramite TMDb.',
                    'link': provider.get('link') or f'https://www.themoviedb.org/{kind}/{id_}'}
            # Re-enrich and re-check archived entries instead of keeping stale ratings/audio/providers.
            for previous in history.get((kind, id_), []):
                event = {k: previous[k] for k in ('date', 'date_basis', 'date_note', 'season',
                         'episode', 'episode_title') if k in previous}
                if 'date_basis' not in event:
                    # Legacy dates were title premieres; do not silently relabel as digital IT.
                    event.update(date_basis='title_original', date_note=
                                 'Data originale del titolo; arrivo nel catalogo italiano da verificare.')
                events.append((event, previous['platform']))
            for platform in platforms:
                for event, historical_platform in events:
                    if historical_platform is not None and historical_platform != platform:
                        continue
                    suffix = f'-s{event["season"]}e{event["episode"]}' if 'episode' in event else ''
                    key = f'{platform}-{kind}-{id_}{suffix}'
                    item = dict(base, **event, id=key, platform=platform,
                                kind=(f'S{event["season"]} · E{event["episode"]}' if suffix else
                                      'Film' if kind == 'movie' else 'Serie'))
                    item.update(audio_fields(item, evidence, today))
                    # Recent events take precedence over their historical copy.
                    if key not in items:
                        items[key] = item
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            errors.append(f'{kind}/{id_}: HTTP {error.code}')
        except Exception as error:
            errors.append(f'{kind}/{id_}: {type(error).__name__}')
    if errors:
        # Never stamp partial scans as successful or discard valid history on an API outage.
        raise RuntimeError('Aggiornamento incompleto; catalogo invariato. ' + '; '.join(errors[:10]))
    ordered = sorted(items.values(), key=lambda x: (x['date'], x['platform'], x['title']), reverse=True)
    return {'schema_version': 2, 'updated_at': now, 'lookback_days': LOOKBACK_DAYS,
            'notice': 'Candidati degli ultimi 14 giorni e archivio di 45 giorni. Date digitali italiane per i film; prima messa in onda per gli episodi. L’arrivo nel singolo catalogo italiano resta da confermare. Audio verificato solo con una fonte specifica.',
            'source_note': 'Metadati e voti: TMDb. Disponibilità: JustWatch tramite TMDb. Questo prodotto utilizza l’API TMDb ma non è approvato o certificato da TMDb.',
            'items': ordered}


def main():
    token = os.environ.get('TMDB_READ_ACCESS_TOKEN', '').strip()
    if not token:
        raise SystemExit('Missing TMDB_READ_ACCESS_TOKEN. Existing data.json unchanged.')
    path = ROOT / 'data.json'
    old = json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    evidence_path = ROOT / 'audio-evidence.json'
    evidence = json.loads(evidence_path.read_text(encoding='utf8')) if evidence_path.exists() else {}
    result = build_catalog(Client(token), old, evidence, dt.datetime.now(ZoneInfo('Europe/Rome')).date())
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    temp.replace(path)
    print('Wrote', len(result['items']), 'entries; all availability checks completed.')


if __name__ == '__main__':
    main()
