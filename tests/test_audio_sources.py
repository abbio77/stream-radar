import pathlib
import sys
import unittest
import datetime as dt
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / 'scripts'))
from audio_sources import AutoAudioResolver, PublicAudioPage, canonical_source, enrich_catalog_audio


def page(audio='Italiano, Inglese', title='Titolo esatto'):
    result = PublicAudioPage()
    result.feed(f'<h1>{title}</h1><h4>Audio</h4><span>{audio}</span><h4>Sottotitoli</h4><span>Italiano</span>')
    return result


class AudioSourcesTests(unittest.TestCase):
    def test_audio_is_not_subtitles_menu_or_translation_bundle(self):
        p = page('Inglese')
        p.feed('<script>{"audio":"Italiano"}</script><p>Trailer italiano</p>')
        self.assertNotIn('Italiano', p.audio_text())
        self.assertTrue(p.matches_title(['Titolo esatto']))
        self.assertFalse(p.matches_title(['Un altro titolo']))
        p = PublicAudioPage()
        p.feed('<h1>Italiano</h1><p>Sottotitoli: Italiano</p>')
        self.assertEqual(p.audio_text(), '')

    def test_source_normalization_rejects_untrusted_or_wrong_endpoints(self):
        self.assertEqual(canonical_source('https://www.netflix.com/title/80115857?x=1', 'Netflix'),
                         'https://www.netflix.com/it/title/80115857')
        for url in ['http://www.netflix.com/title/80115857', 'https://evil.com/title/80115857',
                    'https://user:password@www.netflix.com/title/80115857', 'https://www.netflix.com/login',
                    'https://www.netflix.com:444/title/80115857']:
            self.assertIsNone(canonical_source(url, 'Netflix'))
        self.assertIsNone(canonical_source('https://www.netflix.com/title/80115857', 'Prime Video'))

    def test_identifier_lookup_is_automatic_and_deprecated_claims_ignored(self):
        r = AutoAudioResolver()
        claims = {'P1874': [{'mainsnak': {'datavalue': {'value': '80115857'}}},
                            {'rank': 'deprecated', 'mainsnak': {'datavalue': {'value': '99999999'}}}]}
        with patch.object(r, 'wikidata', return_value=claims):
            self.assertEqual(r.source_urls({'external_ids': {'wikidata_id': 'Q123'}}, 'Netflix'),
                             ['https://www.netflix.com/it/title/80115857'])

    def test_correct_title_and_audio_required_and_failures_do_not_claim_italian(self):
        r = AutoAudioResolver()
        details = {'title': 'Titolo esatto', 'homepage': 'https://www.netflix.com/title/80115857'}
        with patch.object(r, 'page', return_value=page()):
            self.assertEqual(r.check(details, 'Netflix')['status'], 'italian_listed')
        with patch.object(r, 'page', return_value=page(title='Altro film')):
            self.assertEqual(r.check(details, 'Netflix')['status'], 'title_mismatch')
        with patch.object(r, 'page', return_value=page('Inglese')):
            self.assertEqual(r.check(details, 'Netflix')['status'], 'italian_not_listed')
        with patch.object(r, 'page', side_effect=TimeoutError):
            self.assertEqual(r.check(details, 'Netflix')['status'], 'source_unavailable')

    def test_prime_channel_audio_is_not_transferred_to_prime_subscription(self):
        r = AutoAudioResolver()
        details = {'title': 'Titolo esatto', 'homepage': 'https://www.primevideo.com/detail/B012345678'}
        p = page();p.tokens.insert(0, 'Prova Apple TV')
        with patch.object(r, 'page', return_value=p):
            self.assertEqual(r.check(details, 'Prime Video')['status'], 'edition_unconfirmed')
        p.tokens.extend(['Contenuti correlati', 'Guarda con Prime'])
        with patch.object(r, 'page', return_value=p):
            self.assertEqual(r.check(details, 'Prime Video')['status'], 'edition_unconfirmed')
        p.tokens.insert(0, 'Guarda con Prime')
        with patch.object(r, 'page', return_value=p):
            self.assertEqual(r.check(details, 'Prime Video')['status'], 'italian_listed')

    def test_series_indication_is_never_episode_verification_and_existing_proofs_survive(self):
        items = [{'media_type': 'tv', 'tmdb_id': 1, 'platform': 'Netflix', 'audio_italiano': 'unknown'},
                 {'media_type': 'movie', 'tmdb_id': 2, 'platform': 'Netflix', 'audio_italiano': 'unknown'},
                 {'media_type': 'tv', 'tmdb_id': 3, 'platform': 'Apple TV+', 'audio_italiano': 'yes',
                  'audio_source': 'https://tv.apple.com/it/episode/example/123'}]
        r = AutoAudioResolver()
        with patch.object(r, 'check', return_value={'status': 'italian_listed', 'source': 'https://www.netflix.com/it/title/80115857'}):
            counts = enrich_catalog_audio(items, {('tv', 1): {}, ('movie', 2): {}, ('tv', 3): {}}, dt.date(2026, 10, 20), r)
        self.assertEqual(items[0]['audio_italiano'], 'unknown')
        self.assertEqual(items[0]['audio_title_italiano'], 'yes')
        self.assertEqual(items[1]['audio_italiano'], 'yes')
        self.assertEqual(items[2]['audio_source'], 'https://tv.apple.com/it/episode/example/123')
        self.assertEqual(counts['verified_reports'], 2)
        self.assertEqual(counts['series_indications'], 1)

    def test_missing_external_id_lookup_uses_exact_tmdb_ids_and_skips_ambiguity(self):
        import json
        r = AutoAudioResolver()
        bindings = [{'kind': {'value': 'tv'}, 'id': {'value': '42'}, 'item': {'value': 'http://www.wikidata.org/entity/Q123'}}]
        details = {('tv', 42): {'id': 42}}
        with patch.object(r, 'read', return_value=json.dumps({'results': {'bindings': bindings}})) as read:
            self.assertEqual(r.lookup_missing_ids(details, [('tv', 42)]), {('tv', 42): 'Q123'})
            self.assertIn('P4983', read.call_args[0][0])
        bindings.append({'kind': {'value': 'tv'}, 'id': {'value': '42'}, 'item': {'value': 'http://www.wikidata.org/entity/Q456'}})
        with patch.object(r, 'read', return_value=json.dumps({'results': {'bindings': bindings}})):
            self.assertEqual(r.lookup_missing_ids(details, [('tv', 42)]), {})
        self.assertEqual(canonical_source('https://tv.apple.com/show/umc.cmc.123', 'Apple TV+'),
                         'https://tv.apple.com/it/show/umc.cmc.123')

    def test_request_budget_stops_before_network(self):
        r = AutoAudioResolver(request_limit=0)
        with self.assertRaises(RuntimeError):
            r.read('https://www.netflix.com/it/title/80115857')


if __name__ == '__main__':
    unittest.main()
