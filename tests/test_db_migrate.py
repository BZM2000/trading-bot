from app.db.migrate import scrub_url


def test_scrub_url_masks_credentials():
    url = "postgresql+psycopg://user:secret@host:5432/db"
    assert scrub_url(url) == "***@host:5432/db"


def test_scrub_url_returns_plain_when_no_credentials():
    url = "sqlite:///./trading_bot.db"
    assert scrub_url(url) == url
