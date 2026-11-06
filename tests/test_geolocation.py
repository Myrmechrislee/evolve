import gzip
import io
import json
from ipaddress import IPv6Address, ip_address
from unittest.mock import Mock

import pytest

from evolve import create_app, geolocation
from evolve.geolocation import chinese_region
from scripts.refresh_language_regions import build_regions


@pytest.mark.parametrize(('address', 'region'), [
    ('223.5.5.5', 'CN'), ('168.95.1.1', 'TW'), ('203.198.7.66', 'HK'),
    ('202.175.1.1', 'MO'), ('2400:3200::1', 'CN'), ('2001:b000::1', 'TW'),
    ('::ffff:223.5.5.5', 'CN'),
])
def test_bundled_country_data_recognizes_chinese_regions(address, region):
    assert chinese_region(address) == region


@pytest.mark.parametrize('address', ['8.8.8.8', '127.0.0.1', '::1', '192.168.1.1', '10.1.2.3',
                                     '169.254.1.1', 'fc00::1', 'bad-address', None])
def test_other_regions_private_and_invalid_addresses_do_not_force_chinese(address):
    assert chinese_region(address) is None


def test_singapore_and_both_ip_versions_are_present():
    with gzip.open(geolocation.REGION_DATA, 'rt') as source:
        data = json.load(source)
    assert set(data['regions']) == {'CN', 'TW', 'HK', 'MO', 'SG'}
    assert len(data['source_sha256']) == 64
    assert data['license'] == 'CC-BY-4.0'
    for version, rows in data['ranges'].items():
        assert rows
        for region in data['regions']:
            row = next(row for row in rows if row[2] == region)
            address = ip_address(row[0]) if version == '4' else IPv6Address(row[0])
            assert chinese_region(address) == region
            assert chinese_region(ip_address(row[1]) if version == '4' else IPv6Address(row[1])) == region


@pytest.mark.parametrize('address', ['223.5.5.5', '168.95.1.1', '2400:3200::1'])
def test_first_homepage_is_chinese_for_region_even_with_english_browser(client, address):
    response = client.get('/', environ_overrides={'REMOTE_ADDR': address}, headers={'Accept-Language': 'en-US,en;q=0.9'})
    assert response.headers['Content-Language'] == 'zh-Hans'
    assert '<html lang="zh-Hans">' in response.get_data(as_text=True)
    assert '每一天。' in response.get_data(as_text=True)
    assert 'evolve_language=' not in '\n'.join(response.headers.getlist('Set-Cookie'))
    assert response.cache_control.private
    assert 'Accept-Language' in response.vary and 'Cookie' in response.vary


@pytest.mark.parametrize(('language', 'expected'), [('en', 'en'), ('zh-Hans', 'zh-Hans')])
def test_manual_choice_skips_geolocation_and_survives_region_change(client, monkeypatch, language, expected):
    lookup = Mock(side_effect=AssertionError('A manual language must take priority'))
    monkeypatch.setattr(geolocation, 'chinese_region', lookup)
    client.set_cookie('evolve_language', language)
    for address in ['223.5.5.5', '8.8.8.8']:
        response = client.get('/', environ_overrides={'REMOTE_ADDR': address})
        assert response.headers['Content-Language'] == expected
    lookup.assert_not_called()


@pytest.mark.parametrize(('header', 'expected'), [
    ('zh-TW,zh;q=0.9,en;q=0.8', 'zh-Hans'), ('zh-Hant-HK,en;q=0.5', 'zh-Hans'),
    ('en-US,en;q=0.9,zh;q=0.5', 'en'), ('zh;q=0,en;q=1', 'en'), ('fr-FR', 'en'), ('', 'en'),
])
def test_private_connections_use_browser_preference(client, header, expected):
    response = client.get('/', headers={'Accept-Language': header})
    assert response.headers['Content-Language'] == expected


def test_untrusted_country_and_forwarded_headers_cannot_choose_language(app, client):
    app.config['LANGUAGE_TRUSTED_PROXIES'] = ''
    response = client.get('/', environ_overrides={'REMOTE_ADDR': '8.8.8.8'}, headers={
        'X-Forwarded-For': '223.5.5.5', 'CF-IPCountry': 'CN', 'X-Country-Code': 'TW', 'X-Real-IP': '168.95.1.1',
    })
    assert response.headers['Content-Language'] == 'en'


def test_trusted_proxy_uses_first_untrusted_hop_from_right(app, client):
    app.config['LANGUAGE_TRUSTED_PROXIES'] = '10.0.0.0/8'
    def visit(forwarded):
        return client.get('/', environ_overrides={'REMOTE_ADDR': '10.0.0.1'}, headers={'X-Forwarded-For': forwarded})
    assert visit('223.5.5.5').headers['Content-Language'] == 'zh-Hans'
    assert visit('168.95.1.1, 10.0.0.2').headers['Content-Language'] == 'zh-Hans'
    assert visit('223.5.5.5, 8.8.8.8').headers['Content-Language'] == 'en'
    assert visit('garbage').headers['Content-Language'] == 'en'
    assert visit(','.join(['223.5.5.5'] * 21)).headers['Content-Language'] == 'en'
    # Forwarded host/scheme are never used for callback origins or request URLs.
    response = client.get('/', environ_overrides={'REMOTE_ADDR': '10.0.0.1'}, headers={
        'X-Forwarded-For': '223.5.5.5', 'X-Forwarded-Host': 'attacker.test', 'X-Forwarded-Proto': 'https',
    })
    assert 'attacker.test' not in response.get_data(as_text=True)


def test_trusted_ipv6_proxy_supports_ipv6_visitors(app, client):
    app.config['LANGUAGE_TRUSTED_PROXIES'] = 'fd00::/8'
    response = client.get('/', environ_overrides={'REMOTE_ADDR': 'fd00::1'}, headers={'X-Forwarded-For': '2400:3200::1'})
    assert response.headers['Content-Language'] == 'zh-Hans'


def test_missing_region_file_falls_back_without_network(app, client, tmp_path, monkeypatch):
    monkeypatch.setattr(geolocation, 'REGION_DATA', tmp_path / 'missing.gz')
    lookup = Mock(side_effect=AssertionError('No external lookup should happen'))
    monkeypatch.setattr('requests.get', lookup)
    geolocation.region_ranges.cache_clear()
    try:
        response = client.get('/', environ_overrides={'REMOTE_ADDR': '223.5.5.5'}, headers={'Accept-Language': 'zh-TW'})
        assert response.status_code == 200
        assert response.headers['Content-Language'] == 'zh-Hans'
        lookup.assert_not_called()
    finally:
        geolocation.region_ranges.cache_clear()


def test_bad_trusted_proxy_configuration_fails_at_startup():
    with pytest.raises(RuntimeError, match='LANGUAGE_TRUSTED_PROXIES'):
        create_app({'SECRET_KEY': 'only-a-test', 'LANGUAGE_TRUSTED_PROXIES': 'invalid-network'})


def test_country_import_keeps_only_selected_nonoverlapping_ranges():
    rows = '1.0.0.1,1.0.0.1,CN\n1.0.0.2,1.0.0.2,TW\n1.0.0.3,1.0.0.3,HK\n1.0.0.4,1.0.0.4,MO\n1.0.0.5,1.0.0.5,SG\n8.8.8.0,8.8.8.255,US\n'
    result = build_regions(io.StringIO(rows), '2026-11', 'source-hash')
    assert len(result['ranges']['4']) == 5
    assert result['source_records'] == 6
    with pytest.raises(ValueError, match='missing'):
        build_regions(io.StringIO('1.0.0.1,1.0.0.1,CN\n'), '2026-11', 'source-hash')
    with pytest.raises(ValueError, match='overlap'):
        build_regions(io.StringIO(rows + '1.0.0.1,1.0.0.2,CN\n'), '2026-11', 'source-hash')
