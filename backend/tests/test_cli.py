import asyncio
import json
import re
from pathlib import Path

from PIL import Image as PILImage
from PIL.TiffImagePlugin import IFDRational
from click.testing import CliRunner

from myphoto.cli import cli
from myphoto.config import DEFAULT_CONFIG_PATH


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (60, 40), (0, 0, 0)).save(p, "JPEG")


def _jpg_with_exif(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", (60, 40), (0, 0, 0))
    exif = img.getexif()
    exif[0x010F] = "Nikon"
    exif[0x0110] = "Z6"
    sub = exif.get_ifd(0x8769)
    sub[0x829A] = IFDRational(1, 250)
    sub[0x829D] = IFDRational(40, 10)
    sub[0x8827] = 200
    img.save(p, "JPEG", exif=exif.tobytes())


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


# ---------- rescan-exif ----------


def _clear_exif_json(cfg: Path):
    """把 images.exif_json 全部改成 NULL，模拟历史入库未抽 EXIF。"""
    from sqlalchemy import update

    from myphoto.config import load_or_init
    from myphoto.db import make_engine, make_sessionmaker
    from myphoto.models import Image

    async def _run():
        c = load_or_init(cfg)
        db_path = Path(c.data_dir) / "app.db"
        engine = await make_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        sm = await make_sessionmaker(engine)
        async with sm() as s:
            await s.execute(update(Image).values(exif_json=None))
            await s.commit()
        await engine.dispose()

    asyncio.run(_run())


def _read_exif_column(cfg: Path) -> dict[str, str | None]:
    from myphoto.config import load_or_init
    from myphoto.db import make_engine, make_sessionmaker
    from myphoto.models import Image
    from sqlalchemy import select

    async def _run():
        c = load_or_init(cfg)
        db_path = Path(c.data_dir) / "app.db"
        engine = await make_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        sm = await make_sessionmaker(engine)
        async with sm() as s:
            rows = (await s.execute(select(Image))).scalars().all()
            out = {r.filename: r.exif_json for r in rows}
        await engine.dispose()
        return out

    return asyncio.run(_run())


def test_rescan_exif_backfills_null_only(tmp_path):
    photos = tmp_path / "photos"
    _jpg_with_exif(photos / "with.jpg")
    _jpg(photos / "without.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    assert runner.invoke(cli, ["--config", str(cfg), "add-gallery", "H"]).exit_code == 0
    assert runner.invoke(cli, [
        "--config", str(cfg), "add-root", "H", "R", str(photos.resolve())
    ]).exit_code == 0
    assert runner.invoke(cli, ["--config", str(cfg), "rescan"]).exit_code == 0

    # 初次扫描后：with.jpg 已有 exif_json，without.jpg 为 NULL
    before = _read_exif_column(cfg)
    assert before["with.jpg"] is not None
    assert before["without.jpg"] is None

    # 手动清空 exif_json，模拟旧版本入库
    _clear_exif_json(cfg)
    cleared = _read_exif_column(cfg)
    assert all(v is None for v in cleared.values())

    r = runner.invoke(cli, ["--config", str(cfg), "rescan-exif"])
    assert r.exit_code == 0, r.output
    # updated=1 (with.jpg has EXIF), without.jpg 抽不到 EXIF 保持 NULL
    assert "updated=1" in r.output

    after = _read_exif_column(cfg)
    assert after["with.jpg"] is not None
    data = json.loads(after["with.jpg"])
    assert data["Make"] == "Nikon"
    assert data["ExposureTime"] == "1/250"
    assert after["without.jpg"] is None


def test_rescan_exif_missing_file_counts_as_missing(tmp_path):
    photos = tmp_path / "photos"
    _jpg_with_exif(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "H"])
    runner.invoke(cli, [
        "--config", str(cfg), "add-root", "H", "R", str(photos.resolve())
    ])
    runner.invoke(cli, ["--config", str(cfg), "rescan"])
    _clear_exif_json(cfg)

    # 删除文件，模拟 root 内容变动
    (photos / "a.jpg").unlink()

    r = runner.invoke(cli, ["--config", str(cfg), "rescan-exif"])
    assert r.exit_code == 0, r.output
    assert "missing=1" in r.output
