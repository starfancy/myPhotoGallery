import re
from pathlib import Path

from PIL import Image as PILImage
from click.testing import CliRunner

from myphoto.cli import cli
from myphoto.config import DEFAULT_CONFIG_PATH


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (60, 40), (0, 0, 0)).save(p, "JPEG")


def test_add_gallery_and_root_and_rescan(tmp_path):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    _jpg(photos / "sub" / "b.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()

    r = runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "Main", str(photos.resolve())])
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["--config", str(cfg), "rescan"])
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["--config", str(cfg), "list"])
    assert r.exit_code == 0, r.output
    assert "Home" in r.output
    assert re.search(r"2 images", r.output)


def test_add_root_missing_gallery(tmp_path):
    cfg = tmp_path / "config.toml"
    r = CliRunner().invoke(cli, ["--config", str(cfg), "add-root", "Nope", "L", str(tmp_path)])
    assert r.exit_code != 0


def test_add_root_missing_path(tmp_path):
    cfg = tmp_path / "config.toml"
    CliRunner().invoke(cli, ["--config", str(cfg), "add-gallery", "G"])
    r = CliRunner().invoke(cli, ["--config", str(cfg), "add-root", "G", "L", str(tmp_path / "nope")])
    assert r.exit_code != 0


def test_cli_uses_project_config_when_option_omitted(monkeypatch):
    seen: list[str | None] = []

    async def fake_bootstrap(config_path):
        seen.append(config_path)
        raise RuntimeError("stop after config capture")

    monkeypatch.setattr("myphoto.cli._bootstrap", fake_bootstrap)
    result = CliRunner().invoke(cli, ["list"])
    assert result.exit_code != 0  # RuntimeError
    assert seen == [None]


def test_reset_password_default_admin(tmp_path):
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    # First, ensure admin user exists by running add-gallery (which bootstraps admin)
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "ResetTest"])

    # Reset password with auto-generation
    r = runner.invoke(cli, ["--config", str(cfg), "reset-password"])
    assert r.exit_code == 0, r.output
    assert "password for 'admin' has been reset to:" in r.output


def test_reset_password_explicit_value(tmp_path):
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "ResetExplicit"])

    r = runner.invoke(cli, ["--config", str(cfg), "reset-password", "--password", "mynewpass123"])
    assert r.exit_code == 0, r.output
    assert "password for 'admin' has been reset." in r.output


def test_reset_password_unknown_user(tmp_path):
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    # Bootstrap first
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "ResetUnknown"])

    r = runner.invoke(cli, ["--config", str(cfg), "reset-password", "--username", "nobody"])
    assert r.exit_code != 0
    assert "user 'nobody' not found" in r.output


def test_cli_passes_explicit_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    seen: list[str | None] = []

    async def fake_bootstrap(config_path):
        seen.append(config_path)
        raise RuntimeError("stop after config capture")

    monkeypatch.setattr("myphoto.cli._bootstrap", fake_bootstrap)
    result = CliRunner().invoke(cli, ["--config", str(cfg), "list"])
    assert result.exit_code != 0  # RuntimeError
    assert seen == [str(cfg)]
