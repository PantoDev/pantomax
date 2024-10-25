import pytest
from panto.services.config_storage.db_config_storage import _get_org_url

@pytest.mark.parametrize("url, expected", [
    ("https://github.com/organization/repo/", "https://github.com/organization"),
    ("https://github.com/organization/repo", "https://github.com/organization"),
    ("https://github.com/organization/repo.git", "https://github.com/organization"),
    ("http://example.com/org/repo", "http://example.com/org"),
    ("https://subdomain.example.com/org/repo", "https://subdomain.example.com/org"),
    ("https://example.com/", "https://example.com"),
    ("https://example.com", "https://example.com"),
    ("https://example.com/org", "https://example.com/org"),
    ("https://example.com/org/", "https://example.com/org"),
])
def test_get_org_url(url, expected):
    assert _get_org_url(url) == expected
