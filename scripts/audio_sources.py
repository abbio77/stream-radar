"""Public official audio metadata. No login, player APIs, or inferred dubbing."""
import concurrent.futures
import datetime as dt
from functools import lru_cache
from html.parser import HTMLParser
import json
import re
import threading
import unicodedata
import urllib.parse
import urllib.request

MAX_BYTES = 8_000_000
SOURCE_HOSTS = {
    'Netflix': {'www.netflix.com', 'netflix.com'},
    'Prime Video': {'www.primevideo.com', 'primevideo.com'},
    'Crunchyroll': {'www.crunchyroll.com', 'crunchyroll.com'},
    'Apple TV+': {'tv.apple.com'},
}


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value)).casefold()
    return ' '.join(re.sub(r'[^\w\s]', ' ', ''.join(c for c in value if not unicodedata.combining(c))).split())


class PublicAudioPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tokens = []
        self.titles = []
        self.skip = 0
        self.in_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'svg', 'noscript'):
            self.skip += 1
        if tag in ('h1', 'title') and not self.skip:
            self.in_title = True
            self.title_parts = []
        if tag == 'meta' and attrs.get('property') == 'og:title':
            self.titles.append(attrs.get('content', ''))

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'svg', 'noscript'):
            self.skip = max(0, self.skip - 1)
        if tag in ('h1', 'title') and self.in_title:
            self.titles.append(' '.join(self.title_parts))
            self.in_title = False

    def handle_data(self, value):
        if self.skip or not value.strip():
            return
        self.tokens.append(value.strip())
        if self.in_title:
            self.title_parts.append(value.strip())

    def matches_title(self, titles):
        return any(re.search(r'(?<!\w)' + re.escape(normalized(expected)) + r'(?!\w)', normalized(actual))
                   for expected in titles if expected and len(normalized(expected)) >= 3
                   for actual in self.titles)

    def audio_text(self):
        labels = {'audio', 'lingue audio', 'audio languages'}
        endings = {'sottotitoli', 'subtitles', 'lingue sottotitoli', 'subtitle languages'}
        for index, token in enumerate(self.tokens):
            if normalized(token) not in labels:
                continue
            section = []
            for following in self.tokens[index + 1:index + 201]:
                if normalized(following) in endings:
                    return ' '.join(section)
                section.append(following)
        return ''  # No complete, explicit Audio section: never scan the whole page for Italiano.


def canonical_source(url, platform):
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in SOURCE_HOSTS.get(platform, set()) or parsed.username or parsed.password or parsed.port:
            return None
        if platform == 'Netflix':
            match = re.search(r'/(?:title|watch)/(\d{6,8})(?:/|$)', parsed.path)
            return 'https://www.netflix.com/it/title/' + match[1] if match else None
        if platform == 'Prime Video':
            match = re.search(r'/detail/(?:[^/]+/)?([A-Z0-9]{10,32})(?:/|$)', parsed.path)
            return 'https://www.primevideo.com/-/it/detail/' + match[1] if match else None
        if platform == 'Crunchyroll':
            match = re.search(r'/(series|watch)/([A-Z0-9]{8,15})(?:/|$)', parsed.path)
            return f'https://www.crunchyroll.com/it/{match[1]}/{match[2]}' if match else None
        if platform == 'Apple TV+' and re.search(r'/(movie|show|episode)/', parsed.path):
            path = parsed.path
            if re.match(r'^/(movie|show|episode)/', path):
                path = '/it' + path
            else:
                path = re.sub(r'^/[a-z]{2}(?:-[a-z]{2})?/', '/it/', path)
            return 'https://tv.apple.com' + path if re.match(r'^/it/(movie|show|episode)/', path) else None
    except (ValueError, TypeError):
        pass
    return None


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        old, new = urllib.parse.urlparse(request.full_url), urllib.parse.urlparse(newurl)
        if new.scheme != 'https' or new.hostname != old.hostname:
            raise ValueError('Unexpected source redirect')
        return super().redirect_request(request, fp, code, message, headers, newurl)


class AutoAudioResolver:
    def __init__(self, request_limit=180):
        self.request_limit = request_limit
        self.request_count = 0
        self.lock = threading.Lock()

    def read(self, url):
        with self.lock:
            if self.request_count >= self.request_limit:
                raise RuntimeError('Audio request budget exhausted')
            self.request_count += 1
        request = urllib.request.Request(url, headers={
            'User-Agent': 'StreamRadar/2.1 (+https://abbio77.github.io/stream-radar/)',
            'Accept-Language': 'it-IT,it;q=0.9', 'Accept': 'text/html,application/json'})
        with urllib.request.build_opener(OfficialRedirect()).open(request, timeout=10) as response:
            page = response.read(MAX_BYTES + 1)
        if len(page) > MAX_BYTES:
            raise ValueError('Source too large')
        return page.decode('utf8')

    @lru_cache(maxsize=256)
    def wikidata(self, entity_id):
        if not re.fullmatch(r'Q\d+', entity_id or ''):
            return {}
        data = json.loads(self.read(f'https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json'))
        return data.get('entities', {}).get(entity_id, {}).get('claims', {})

    def lookup_missing_ids(self, details_by_id, keys):
        missing = [(kind, id_) for kind, id_ in keys
                   if isinstance(details_by_id.get((kind, id_), {}).get('id'), int)
                   and not details_by_id[(kind, id_)].get('external_ids', {}).get('wikidata_id')][:100]
        if not missing:
            return {}
        values = ' '.join(f'(wdt:{"P4947" if kind == "movie" else "P4983"} "{int(id_)}" "{kind}")' for kind, id_ in missing)
        query = 'PREFIX wdt: <http://www.wikidata.org/prop/direct/> SELECT ?item ?id ?kind WHERE { VALUES (?property ?id ?kind) { ' + values + ' } ?item ?property ?id . }'
        url = 'https://query.wikidata.org/sparql?' + urllib.parse.urlencode({'query': query, 'format': 'json'})
        try:
            data = json.loads(self.read(url))
            found = {}
            allowed = set(missing)
            for row in data.get('results', {}).get('bindings', []):
                key = (row['kind']['value'], int(row['id']['value']))
                entity = row['item']['value'].rsplit('/', 1)[-1]
                if key in allowed and re.fullmatch(r'Q\d+', entity):
                    found.setdefault(key, set()).add(entity)
            return {key: next(iter(entities)) for key, entities in found.items() if len(entities) == 1}
        except Exception:
            return {}  # Optional lookup failure must not prevent direct homepage checks.

    def source_urls(self, details, platform):
        urls = []
        homepage = canonical_source(details.get('homepage'), platform)
        if homepage:
            urls.append(homepage)
        entity = details.get('external_ids', {}).get('wikidata_id')
        properties = {'Netflix': ['P1874'], 'Prime Video': ['P14440', 'P8055'],
                      'Crunchyroll': ['P11330'], 'Apple TV+': ['P9586', 'P9751']}
        if entity:
            claims = self.wikidata(entity)
            tmdb_property = 'P4947' if details.get('title') else 'P4983'
            mapped_ids = {str(c.get('mainsnak', {}).get('datavalue', {}).get('value')) for c in claims.get(tmdb_property, []) if c.get('rank') != 'deprecated'}
            if mapped_ids and str(details.get('id')) not in mapped_ids:
                return urls
            for prop in properties.get(platform, []):
                for claim in claims.get(prop, []):
                    if claim.get('rank') == 'deprecated':
                        continue
                    value = claim.get('mainsnak', {}).get('datavalue', {}).get('value')
                    if not isinstance(value, str):
                        continue
                    if platform == 'Netflix' and re.fullmatch(r'\d{6,8}', value):
                        urls.append('https://www.netflix.com/it/title/' + value)
                    elif platform == 'Prime Video' and re.fullmatch(r'[A-Z0-9]{10,32}', value):
                        urls.append('https://www.primevideo.com/-/it/detail/' + value)
                    elif platform == 'Crunchyroll' and re.fullmatch(r'[A-Z0-9]{8,15}', value):
                        urls.append('https://www.crunchyroll.com/it/series/' + value)
                    elif platform == 'Apple TV+' and re.fullmatch(r'umc\.cmc\.[a-z0-9]+', value):
                        media = 'movie' if prop == 'P9586' else 'show'
                        urls.append(f'https://tv.apple.com/it/{media}/title/{value}')
        return list(dict.fromkeys(urls))[:2]

    @lru_cache(maxsize=256)
    def page(self, url):
        page = PublicAudioPage()
        page.feed(self.read(url))
        return page

    def check(self, details, platform):
        if platform not in SOURCE_HOSTS:
            return {'status': 'unsupported'}
        try:
            urls = self.source_urls(details, platform)
        except Exception:
            # A Wikidata outage must not block a usable direct official homepage.
            direct = canonical_source(details.get('homepage'), platform)
            urls = [direct] if direct else []
            if not urls:
                return {'status': 'source_unavailable'}
        if not urls:
            return {'status': 'no_source'}
        result = {'status': 'source_unavailable', 'source': urls[0]}
        titles = [details.get(k) for k in ('title', 'name', 'original_title', 'original_name')]
        for url in urls:
            try:
                page = self.page(url)
                if not page.matches_title(titles):
                    result = {'status': 'title_mismatch', 'source': url}
                    continue
                audio = page.audio_text()
                if not audio:
                    result = {'status': 'not_exposed', 'source': url}
                    continue
                if not re.search(r'\b(?:Italiano|Italian)\b', audio, flags=re.I):
                    result = {'status': 'italian_not_listed', 'source': url}
                    continue
                if platform == 'Prime Video' and not re.search(
                        r'(?:guarda con prime|incluso con prime|watch with prime|iscriviti a prime e guarda)',
                        re.split(r'\b(?:Contenuti correlati|Related|Altri titoli)\b', ' '.join(page.tokens), maxsplit=1, flags=re.I)[0], flags=re.I):
                    return {'status': 'edition_unconfirmed', 'source': url}
                return {'status': 'italian_listed', 'source': url}
            except Exception:
                continue
        return result


def enrich_catalog_audio(items, details_by_id, today, resolver=None):
    resolver = resolver or AutoAudioResolver()
    groups = {}
    for item in items:
        groups.setdefault((item['media_type'], item['tmdb_id'], item['platform']), []).append(item)
    lookup_details = {key: dict(details, external_ids=dict(details.get('external_ids') or {})) for key, details in details_by_id.items()}
    supported_keys = list(dict.fromkeys((kind, id_) for kind, id_, platform in groups if platform in SOURCE_HOSTS))
    for key, entity in resolver.lookup_missing_ids(lookup_details, supported_keys).items():
        lookup_details[key]['external_ids']['wikidata_id'] = entity
    def check(group):
        kind, id_, platform = group
        return group, resolver.check(lookup_details[(kind, id_)], platform)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(pool.map(check, groups))
    counts = {'verified_reports': 0, 'series_indications': 0, 'unconfirmed_reports': 0}
    notes = {'unsupported': 'Controllo automatico non ancora disponibile per questa piattaforma.',
             'no_source': 'Scheda ufficiale non ancora associata automaticamente al titolo.',
             'source_unavailable': 'Fonte ufficiale non accessibile in questo aggiornamento.',
             'title_mismatch': 'Identità della scheda ufficiale non confermata.',
             'not_exposed': 'La pagina pubblica non espone un elenco audio leggibile.',
             'italian_not_listed': 'Italiano non rilevato nell’elenco pubblico; verificare nel lettore della piattaforma.',
             'edition_unconfirmed': 'Pagina Prime Video trovata, ma edizione inclusa in Prime non confermata.'}
    for group, entries in groups.items():
        result = results[group]
        for item in entries:
            if item.get('audio_italiano') in ('yes', 'sub'):
                counts['verified_reports'] += 1
                item['audio_check_status'] = 'verified'
                continue
            item['audio_check_status'] = result['status']
            if result.get('source'):
                item['audio_lookup_source'] = result['source']
            if result['status'] == 'italian_listed':
                if item['media_type'] == 'movie':
                    item.update(audio_italiano='yes', audio_source=result['source'],
                                audio_checked_at=today.isoformat(), audio_scope='Film · scheda ufficiale italiana',
                                audio_note='Italiano elencato nell’audio della scheda ufficiale, controllata automaticamente.')
                    counts['verified_reports'] += 1
                else:
                    item.update(audio_title_italiano='yes', audio_title_source=result['source'],
                                audio_title_checked_at=today.isoformat(), audio_note=
                                'Italiano indicato per la serie nella scheda ufficiale. La lingua di questo episodio resta da confermare.')
                    counts['series_indications'] += 1
            else:
                item['audio_note'] = notes.get(result['status'], notes['source_unavailable'])
                counts['unconfirmed_reports'] += 1
    return counts
