from typer.testing import CliRunner

from openmind.cli.main import app


def test_uninstall_dry_run_keeps_openmind_home(monkeypatch, tmp_path):
    home = tmp_path / ".openmind"
    home.mkdir()
    (home / "config.toml").write_text("name = 'test'\n", encoding="utf-8")
    monkeypatch.setenv("OPENMIND_HOME", str(home))

    result = CliRunner().invoke(app, ["uninstall", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run only" in result.output
    assert home.exists()
    assert (home / "config.toml").exists()


def test_uninstall_cancel_keeps_openmind_home(monkeypatch, tmp_path):
    home = tmp_path / ".openmind"
    home.mkdir()
    (home / "config.toml").write_text("name = 'test'\n", encoding="utf-8")
    monkeypatch.setenv("OPENMIND_HOME", str(home))

    result = CliRunner().invoke(app, ["uninstall"], input="n\n")

    assert result.exit_code == 0
    assert "Uninstall cancelled" in result.output
    assert home.exists()


def test_uninstall_yes_removes_openmind_home(monkeypatch, tmp_path):
    home = tmp_path / ".openmind"
    (home / "lancedb").mkdir(parents=True)
    (home / "logs").mkdir()
    (home / "config.toml").write_text("name = 'test'\n", encoding="utf-8")
    (home / "openmind.sqlite").write_text("sqlite placeholder", encoding="utf-8")
    monkeypatch.setenv("OPENMIND_HOME", str(home))

    result = CliRunner().invoke(app, ["uninstall", "--yes"])

    assert result.exit_code == 0
    assert "OpenMind local data removed" in result.output
    assert not home.exists()


def test_uninstall_package_flag_removes_package_from_current_environment(
    monkeypatch,
    tmp_path,
):
    home = tmp_path / ".openmind"
    home.mkdir()
    monkeypatch.setenv("OPENMIND_HOME", str(home))
    captured = {}

    class Result:
        returncode = 0

    def fake_run(command, check):
        captured["command"] = command
        captured["check"] = check
        return Result()

    monkeypatch.setattr("openmind.cli.main.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["uninstall", "--yes", "--package"])

    assert result.exit_code == 0
    assert not home.exists()
    assert captured["command"][1:] == ["-m", "pip", "uninstall", "-y", "openmind-core"]
    assert captured["check"] is False
    assert "package removed" in result.output
