from app.config import Settings


def test_cors_origin_allows_with_and_without_trailing_slash():
    settings = Settings(
        cors_origins="https://ledger-nz.pages.dev/,http://localhost:3000/,https://ledger-nz.pages.dev"
    )
    assert settings.cors_origin_list == [
        "https://ledger-nz.pages.dev",
        "https://ledger-nz.pages.dev/",
        "http://localhost:3000",
        "http://localhost:3000/",
    ]
    assert settings.cors_origin_regex == r"^(https://ledger\-nz\.pages\.dev/?|http://localhost:3000/?)$"


def test_cors_regex_matches_browser_origin():
    settings = Settings(cors_origins="https://ledger-nz.pages.dev/")
    import re

    pattern = re.compile(settings.cors_origin_regex or "")
    assert pattern.fullmatch("https://ledger-nz.pages.dev")
    assert pattern.fullmatch("https://ledger-nz.pages.dev/")
    assert not pattern.fullmatch("https://evil.example")
