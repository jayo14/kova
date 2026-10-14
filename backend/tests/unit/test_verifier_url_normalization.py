import pytest
from unittest.mock import MagicMock
from app.engine.verification.verifier import Verifier, _normalize_url_for_matching


def test_normalize_url_for_matching():
    # Slashes and www
    assert _normalize_url_for_matching("https://www.summastudy.com.ng/") == "summastudy.com.ng"
    assert _normalize_url_for_matching("https://summastudy.com.ng") == "summastudy.com.ng"
    assert _normalize_url_for_matching("http://summastudy.com.ng:80/") == "summastudy.com.ng"
    assert _normalize_url_for_matching("https://summastudy.com.ng:443") == "summastudy.com.ng"
    assert _normalize_url_for_matching("www.summastudy.com.ng") == "summastudy.com.ng"
    assert _normalize_url_for_matching("summastudy.com.ng/") == "summastudy.com.ng"

    # Paths
    assert _normalize_url_for_matching("https://www.summastudy.com.ng/explore/") == "summastudy.com.ng/explore"
    assert _normalize_url_for_matching("https://summastudy.com.ng/explore") == "summastudy.com.ng/explore"
    assert _normalize_url_for_matching("/explore/") == "/explore"
    assert _normalize_url_for_matching("/explore") == "/explore"


@pytest.mark.asyncio
async def test_verifier_url_matches_normalized_www_and_slash():
    mock_page = MagicMock()
    mock_page.url = "https://www.summastudy.com.ng/"
    verifier = Verifier(mock_page)

    # Expected without www and without slash
    check = await verifier._check_url_matches("https://summastudy.com.ng")
    assert check.passed is True
    assert check.type == "url_matches"

    # Expected with slash
    check = await verifier._check_url_matches("https://summastudy.com.ng/")
    assert check.passed is True

    # Expected bare domain
    check = await verifier._check_url_matches("summastudy.com.ng")
    assert check.passed is True


@pytest.mark.asyncio
async def test_verifier_url_matches_path_variants():
    mock_page = MagicMock()
    mock_page.url = "https://www.summastudy.com.ng/dashboard/"
    verifier = Verifier(mock_page)

    # Subpath matching
    check = await verifier._check_url_matches("/dashboard")
    assert check.passed is True

    check = await verifier._check_url_matches("https://summastudy.com.ng/dashboard")
    assert check.passed is True
