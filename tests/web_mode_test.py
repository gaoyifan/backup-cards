"""Tests for web mode and daemon CLI commands."""

from typer.testing import CliRunner

from app import cli

runner = CliRunner()


def test_web_command_help_mentions_web_options():
    """Test that web command help includes web-specific options."""
    result = runner.invoke(cli, ["web", "--help"])
    assert result.exit_code == 0
    assert "Serve the Textual UI over HTTP" in result.stdout
    assert "--web-port" in result.stdout


def test_daemon_command_help_mentions_listen_args():
    """Test that daemon command help includes listen arguments."""
    result = runner.invoke(cli, ["daemon", "--help"])
    assert result.exit_code == 0
    assert "Run only the backend API." in result.stdout
    assert "GraphQL listen port" in result.stdout
