from app.config import Settings


def test_cors_origin_strips_trailing_slash():
    settings = Settings(
        cors_origins="https://ledger-nz.pages.dev/,http://localhost:3000/,https://ledger-nz.pages.dev"
    )
    assert settings.cors_origin_list == [
        "https://ledger-nz.pages.dev",
        "http://localhost:3000",
    ]
