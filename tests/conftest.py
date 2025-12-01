"""Shared pytest configuration and fixtures."""

import socket
import sys
from pathlib import Path

import pytest

# Add src to path for test imports
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test (requires backend)")
    config.addinivalue_line("markers", "asyncio: mark test as async test")


def find_free_port() -> int:
    """Find an available port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


@pytest.fixture
def free_port():
    """Fixture to provide a free port."""
    return find_free_port()

