import pytest

from recon import settings


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The burst's 30 s wait after a stop: none in the tests."""
    monkeypatch.setattr(settings, "RECOVER", 0)
