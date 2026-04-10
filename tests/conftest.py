import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_pf9: mark test as requiring TEST_PF9_LIVE=1 and a live PF9 endpoint",
    )
