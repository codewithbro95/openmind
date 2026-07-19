from typer.testing import CliRunner

from openmind import __version__
from openmind.cli.main import OPENMIND_BANNER, app


def test_version_option_reports_installed_version():
    runner = CliRunner()

    long_result = runner.invoke(app, ["--version"])
    short_result = runner.invoke(app, ["-V"])

    assert long_result.exit_code == 0
    assert long_result.output.strip() == f"openmind {__version__}"
    assert short_result.exit_code == 0
    assert short_result.output.strip() == f"openmind {__version__}"


def test_top_level_help_describes_each_command():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for description in (
        "Initialize OpenMind's local app data.",
        "Configure models, sources, and background indexing.",
        "Search indexed local memory.",
        "Ask grounded questions or start an interactive session.",
        "Show OpenMind storage and indexing information.",
        "Clear indexed memory without deleting user files.",
        "Remove OpenMind local data and optionally the package.",
    ):
        assert description in result.output


def test_setup_banner_is_large_ascii_art():
    lines = OPENMIND_BANNER.splitlines()

    assert len(lines) == 6
    assert max(len(line) for line in lines) >= 45
    assert OPENMIND_BANNER.isascii()
