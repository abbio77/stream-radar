import copy
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('update', pathlib.Path(__file__).parents[1] / 'scripts/update.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
TODAY = dt.date(2026, 10, 20)


class FakeClient:
    def __init__(self, available=True, fail=False):
        self.available, self.fail = available, fail
        self.calls = []

    def discover(self, kind, today):
        return [{'id': 1}] if kind == 'movie' else [{'id': 2}]

    def api(self, path, params=None):
        self.calls.append(path)
        if self.fail:
            raise TimeoutError('test outage')
        if 'season/' in path:
            return {'episodes': [{'episode_number': 3, 'air_date': '2026-10-19', 'name': 'Tre'},
                                 {'episode_number': 4, 'air_date': '2026-10-21'}]}
        return {'id': int(path.split('/')[1]), 'title': 'Film', 'name': 'Serie',
                'overview': 'Trama italiana', 'original_language': 'ja',
                'genres': [{'id': 16, 'name': 'Animazione'}],
                'vote_count': 123, 'vote_average': 8.25, 'poster_path': '/fallback.jpg',
                'images': {'posters': [{'file_path': '/italiano.jpg', 'iso_639_1': 'it'}]},
                'watch/providers': {'results': {'IT': {'flatrate': [{'provider_id': 8}] if self.available else [],
                                                       'rent': [{'provider_id': 119}]}}},
                'release_dates': {'results': [{'iso_3166_1': 'IT', 'release_dates': [
                    {'type': 3, 'release_date': '2026-10-20T00:00:00Z'},
                    {'type': 4, 'release_date': '2026-10-18T00:00:00Z'}]}]},
                'seasons': [{'season_number': 1, 'air_date': '2025-01-01'},
                            {'season_number': 2, 'air_date': '2026-10-01'}]}


class UpdateTests(unittest.TestCase):
    def test_digital_date_and_episode_not_title_premiere(self):
        client = FakeClient()
        items = u.build_catalog(client, {}, {}, TODAY)['items']
        self.assertEqual(len(items), 2)
        film = next(i for i in items if i['media_type'] == 'movie')
        episode = next(i for i in items if i['media_type'] == 'tv')
        self.assertEqual(film['date'], '2026-10-18')
        self.assertEqual(film['date_basis'], 'digital_it')
        self.assertEqual((episode['season'], episode['episode']), (2, 3))
        self.assertEqual(episode['date_basis'], 'episode_original')
        self.assertNotIn('tv/2/season/1', client.calls)
        self.assertEqual(film['type'], 'anime')
        self.assertEqual(film['poster'], 'https://image.tmdb.org/t/p/w342/italiano.jpg')
        self.assertEqual(film['rating_count'], 123)
        self.assertEqual(film['audio_italiano'], 'unknown')
        self.assertEqual({i['platform'] for i in items}, {'Netflix'})

    def test_no_rental_or_removed_provider(self):
        self.assertEqual(u.build_catalog(FakeClient(False), {}, {}, TODAY)['items'], [])

    def test_api_error_aborts_instead_of_empty_success(self):
        with self.assertRaises(RuntimeError):
            u.build_catalog(FakeClient(fail=True), {'items': []}, {}, TODAY)

    def test_history_refresh_dedup_and_no_audio_carry_over(self):
        client = FakeClient()
        items = u.build_catalog(client, {}, {}, TODAY)['items']
        for item in items:
            item.update(rating=1, audio_italiano='yes')
        new = u.build_catalog(client, {'items': items}, {}, TODAY)['items']
        self.assertEqual(len(new), len(items))
        self.assertTrue(all(i['rating'] == 8.2 and i['audio_italiano'] == 'unknown' for i in new))

    def test_legacy_date_is_not_relabelled(self):
        old = {'items': [{'id': 'Netflix-tv-2', 'date': '2026-10-14', 'platform': 'Netflix'}]}
        items = u.build_catalog(FakeClient(), old, {}, TODAY)['items']
        legacy = next(i for i in items if i['id'] == 'Netflix-tv-2')
        self.assertEqual(legacy['date_basis'], 'title_original')
        self.assertEqual(legacy['audio_italiano'], 'unknown')

    def test_rating_low_votes_invalid_and_zero(self):
        for value, count in [(8, 9), (float('nan'), 50), (11, 50), (0, 20), (None, 30)]:
            self.assertIsNone(u.rating_fields({'vote_average': value, 'vote_count': count})['rating'])
        self.assertEqual(u.rating_fields({'vote_average': 7.55, 'vote_count': 10})['rating'], 7.5)

    def test_audio_requires_source_region_platform_scope_and_freshness(self):
        item = {'id': 'Netflix-tv-2-s2e3', 'platform': 'Netflix', 'media_type': 'tv', 'season': 2, 'episode': 3}
        record = {'region': 'IT', 'platform': 'Netflix', 'season': 2, 'episode': 3,
                  'checked_at': '2026-10-20', 'expires_at': '2026-11-01', 'status': 'yes',
                  'source_url': 'https://www.netflix.com/it/title/123', 'note': 'Audio italiano E3'}
        self.assertEqual(u.audio_fields(item, {item['id']: record}, TODAY)['audio_italiano'], 'yes')
        for key, value in [('region', 'US'), ('platform', 'Prime Video'), ('season', 1),
                           ('episode', 4), ('checked_at', '2026-08-01'), ('expires_at', '2026-10-19'),
                           ('source_url', 'javascript:alert(1)'), ('note', ''), ('status', 'maybe')]:
            altered = dict(record, **{key: value})
            self.assertEqual(u.audio_fields(item, {item['id']: altered}, TODAY)['audio_italiano'], 'unknown')

    def test_discovery_pagination_and_returning_series(self):
        client = u.Client('test')
        calls = []
        def api(path, params):
            calls.append(params)
            return {'total_pages': 3, 'results': [{'id': params['page']}]}
        client.api = api
        self.assertEqual(len(list(client.discover('tv', TODAY))), 3)
        self.assertIn('air_date.gte', calls[0])
        self.assertNotIn('first_air_date.gte', calls[0])
        self.assertEqual(calls[0]['watch_region'], 'IT')
        self.assertEqual(calls[0]['with_watch_monetization_types'], 'flatrate')

    def test_apple_parser_separates_audio_subtitles_and_ignores_scripts(self):
        parser = u.AppleLanguages()
        parser.feed('<script>Italiano</script><dt data-testid="languages-audio">Audio</dt><dd>Inglese</dd><dt data-testid="languages-subtitles">Sottotitoli</dt><dd>Italiano</dd>')
        self.assertEqual(parser.italian_status(), 'sub')
        parser = u.AppleLanguages()
        parser.feed('<dt data-testid="languages-audio">Audio</dt><dd><span>Italiano (AAC)</span>, Inglese</dd><dt data-testid="languages-subtitles">Sottotitoli</dt><dd>Inglese</dd>')
        self.assertEqual(parser.italian_status(), 'yes')
        parser = u.AppleLanguages()
        parser.feed('<p>Trailer italiano</p><dt data-testid="languages-subtitles">Sottotitoli</dt><dd>Italiano</dd>')
        self.assertEqual(parser.italian_status(), 'unknown')

    def test_apple_audio_requires_correct_episode_and_fails_closed(self):
        item = {'id': 'Apple TV+-tv-1-s2e3', 'platform': 'Apple TV+', 'media_type': 'tv', 'season': 2, 'episode': 3}
        record = {'mode': 'apple_tv', 'platform': 'Apple TV+', 'region': 'IT', 'season': 2, 'episode': 3,
                  'expected_title': 'Serie', 'source_url': 'https://tv.apple.com/it/episode/test/123'}
        page = u.AppleLanguages()
        page.feed('<h1>Serie</h1><p>S2, E3: Trama</p><dt data-testid="languages-audio">Audio</dt><dd>Italiano</dd>')
        with patch.object(u, 'apple_page', return_value=page):
            self.assertEqual(u.audio_fields(item, {item['id']: record}, TODAY)['audio_italiano'], 'yes')
            self.assertEqual(u.audio_fields(item, {item['id']: dict(record, episode=2)}, TODAY)['audio_italiano'], 'unknown')
        with patch.object(u, 'apple_page', side_effect=TimeoutError):
            self.assertEqual(u.audio_fields(item, {item['id']: record}, TODAY)['audio_italiano'], 'unknown')
        for url in ['http://tv.apple.com/it/movie/x/y', 'https://example.com/it/movie/x/y', 'https://tv.apple.com/us/movie/x/y']:
            with self.assertRaises(ValueError):
                u.apple_page(url)

    def test_week_archive_drops_expired_and_future_entries(self):
        old = {'items': [{'id': 'Netflix-tv-2', 'date': day, 'platform': 'Netflix'}
                         for day in ('2026-10-13', '2026-10-14', '2026-10-21')]}
        result = u.build_catalog(FakeClient(), old, {}, TODAY)
        self.assertEqual(result['lookback_days'], 7)
        self.assertTrue(all('2026-10-14' <= i['date'] <= '2026-10-20' for i in result['items']))
        self.assertIn('2026-10-14', [i['date'] for i in result['items']])
        client = u.Client('test')
        queries = []
        client.api = lambda path, params: queries.append(params) or {'results': [], 'total_pages': 1}
        list(client.discover('tv', TODAY))
        self.assertEqual(queries[0]['air_date.gte'], '2026-10-14')
        self.assertEqual(queries[0]['air_date.lte'], '2026-10-20')

    def test_missing_token_does_not_modify_catalog(self):
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'data.json'
            path.write_text('{"items": []}')
            with patch.object(u, 'ROOT', pathlib.Path(root)), patch.dict(u.os.environ, {'TMDB_READ_ACCESS_TOKEN': ''}):
                with self.assertRaises(SystemExit):
                    u.main()
            self.assertEqual(path.read_text(), '{"items": []}')


if __name__ == '__main__':
    unittest.main()
