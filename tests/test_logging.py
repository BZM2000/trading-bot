from app.logging import _normalise_level


def test_normalise_level_lowercase() -> None:
    assert _normalise_level("info") == "INFO"


def test_normalise_level_strips_whitespace() -> None:
    assert _normalise_level("  warn  ") == "WARN"


def test_normalise_level_numeric_passthrough() -> None:
    assert _normalise_level("20") == "20"


def test_normalise_level_empty_defaults() -> None:
    assert _normalise_level("") == "INFO"
