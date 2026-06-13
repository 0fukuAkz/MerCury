"""Tests targeting full coverage of the GeoResolver and geolocation caching."""

import sys
from unittest.mock import MagicMock, patch
from mercury.features.geolocation import GeoResolver, _is_rfc1918_172

def test_is_rfc1918_172():
    assert _is_rfc1918_172("172.16.0.1") is True
    assert _is_rfc1918_172("172.31.255.255") is True
    assert _is_rfc1918_172("172.15.255.255") is False
    assert _is_rfc1918_172("172.32.0.0") is False
    assert _is_rfc1918_172("invalid_ip") is False

def test_geo_resolver_load_geoip_import_error():
    # Force import error for geoip2
    with patch.dict(sys.modules, {"geoip2": None, "geoip2.database": None}):
        r = GeoResolver(db_path="dummy.mmdb")
        with patch("os.path.isfile", return_value=True):
            assert r._load() is False

def test_geo_resolver_load_success():
    mock_reader = MagicMock()
    mock_geoip = MagicMock()
    mock_geoip.database.Reader.return_value = mock_reader
    
    with patch.dict(sys.modules, {"geoip2": mock_geoip, "geoip2.database": mock_geoip.database}), \
         patch("os.path.isfile", return_value=True):
        r = GeoResolver(db_path="dummy.mmdb")
        assert r._load() is True
        assert r._reader == mock_reader
        
        # Test cache hit / miss
        mock_city_record = MagicMock()
        mock_city_record.country.name = "Canada"
        mock_city_record.country.iso_code = "CA"
        mock_city_record.city.name = "Toronto"
        mock_city_record.subdivisions.most_specific.name = "Ontario"
        mock_city_record.subdivisions.most_specific.iso_code = "ON"
        mock_city_record.location.time_zone = "America/Toronto"
        mock_city_record.continent.name = "North America"
        mock_city_record.postal.code = "M5V"
        
        mock_reader.city.return_value = mock_city_record
        
        res = r.resolve("8.8.8.8")
        assert res["country"] == "Canada"
        assert res["city"] == "Toronto"
        
        # Second call should hit cache
        res2 = r.resolve("8.8.8.8")
        assert res2["country"] == "Canada"
        # mock_reader.city should only be called once
        mock_reader.city.assert_called_once()
        
        # Test close
        r.close()
        assert r._reader is None
        assert len(r._cache) == 0

def test_geo_resolver_load_exception():
    mock_geoip = MagicMock()
    mock_geoip.database.Reader.side_effect = Exception("failed to read mmdb format")
    with patch.dict(sys.modules, {"geoip2": mock_geoip, "geoip2.database": mock_geoip.database}), \
         patch("os.path.isfile", return_value=True):
        r = GeoResolver(db_path="dummy.mmdb")
        assert r._load() is False

def test_geo_resolver_cache_eviction():
    mock_reader = MagicMock()
    mock_geoip = MagicMock()
    mock_geoip.database.Reader.return_value = mock_reader
    
    with patch.dict(sys.modules, {"geoip2": mock_geoip, "geoip2.database": mock_geoip.database}), \
         patch("os.path.isfile", return_value=True):
        r = GeoResolver(db_path="dummy.mmdb")
        assert r._load() is True
        
        # Seed 1024 mock entries in cache to test eviction
        for i in range(1024):
            r._cache[f"1.1.1.{i}"] = {"city": f"City_{i}"}
            r._cache_keys.append(f"1.1.1.{i}")
            
        # Add another lookup (should evict 1.1.1.0)
        mock_city_record = MagicMock()
        mock_city_record.country.name = "USA"
        mock_reader.city.return_value = mock_city_record
        
        res = r.resolve("8.8.8.8")
        assert "1.1.1.0" not in r._cache
        assert "8.8.8.8" in r._cache
        assert len(r._cache) == 1024
