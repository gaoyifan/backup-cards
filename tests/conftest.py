"""Shared pytest configuration and fixtures."""

import socket
import sys
import tempfile
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


@pytest.fixture
async def fresh_db():
    """Fixture that provides a fresh database for each test.

    Resets the global database state before and after each test.
    """
    import backend.db as db_module

    # Reset globals
    db_module._engine = None
    db_module._SessionFactory = None

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        await db_module.init_db(db_path)
        await db_module.create_schema()
        yield db_path

    # Cleanup after test
    if db_module._engine:
        await db_module._engine.dispose()
    db_module._engine = None
    db_module._SessionFactory = None
