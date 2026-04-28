import socket
import os

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_pf9: mark test as requiring TEST_PF9_LIVE=1 and a live PF9 endpoint",
    )
    config.addinivalue_line(
        "markers",
        "live_tenant: mark test as requiring a running tenant portal stack",
    )


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def api_server_available() -> bool:
    """True when the main API server is reachable on TEST_API_URL / localhost:8000."""
    url = os.getenv("TEST_API_URL", "http://localhost:8000")
    # Parse host:port from the URL
    host = url.split("://")[-1].split("/")[0].split(":")[0]
    port_str = url.split("://")[-1].split("/")[0].split(":")[1] if ":" in url.split("://")[-1].split("/")[0] else ("443" if url.startswith("https") else "8000")
    return _is_port_open(host, int(port_str))


@pytest.fixture(scope="session")
def tenant_direct_available() -> bool:
    """True when the tenant portal backend is reachable on TENANT_DIRECT_URL / localhost:8010."""
    url = os.getenv("TENANT_DIRECT_URL", "http://localhost:8010")
    host = url.split("://")[-1].split("/")[0].split(":")[0]
    port_str = url.split("://")[-1].split("/")[0].split(":")[1] if ":" in url.split("://")[-1].split("/")[0] else "8010"
    return _is_port_open(host, int(port_str))
