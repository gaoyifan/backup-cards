from typer.testing import CliRunner

from main import cli

runner = CliRunner()


def test_web_and_headless_flags_are_incompatible():
    result = runner.invoke(cli, ["--web", "--headless"])
    assert result.exit_code != 0
    assert "Cannot combine --web with --headless" in result.stderr


def test_web_and_frontend_only_flags_are_incompatible():
    result = runner.invoke(cli, ["--web", "--frontend-only"])
    assert result.exit_code != 0
    assert "Cannot combine --web with --frontend-only" in result.stderr

