import re
from pathlib import Path

from PIL import Image as PILImage
from click.testing import CliRunner

from myphoto.cli import cli


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
