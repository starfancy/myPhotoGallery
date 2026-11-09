"""一次性种子脚本：把现有 3 支合成预设从 frontend/public/filters/ 拷到
backend/data/luts/synthetic/，并预填 DB 元数据（enabled=1）。

富士 5 支（provia/velvia/astia/classic_chrome/acros）需从
https://github.com/YahiaAngelo/Film-Luts 手动下载到 backend/data/luts/fujifilm/
后再次运行本脚本（幂等：已存在的 file_path 跳过）。

用法：
    cd backend
    python -m scripts.seed_luts
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# 让脚本能 import myphoto
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from myphoto.config import load_or_init, resolve_config_path  # noqa: E402
from myphoto.db import make_engine, make_sessionmaker  # noqa: E402
from myphoto.lut_scanner import scan_luts  # noqa: E402
from myphoto.schema_init import ensure_schema_and_admin  # noqa: E402


SYNTHETIC_PRESETS = [
    # (source_rel_in_frontend, target_filename_in_luts_dir, label)
    ("warm.cube", "warm.cube", "暖色调"),
    ("cool.cube", "cool.cube", "冷色调"),
    ("mono.cube", "mono.cube", "黑白"),
]


async def main() -> int:
    config_path = resolve_config_path(None)
    cfg = load_or_init(config_path)
    luts_dir = Path(cfg.data_dir) / "luts"
    luts_dir.mkdir(parents=True, exist_ok=True)

    # 1. 拷合成预设
    src_dir = ROOT.parent / "frontend" / "public" / "filters"
    synth_dir = luts_dir / "synthetic"
    synth_dir.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name, _label in SYNTHETIC_PRESETS:
        src = src_dir / src_name
        dst = synth_dir / dst_name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            print(f"copied {src_name} -> synthetic/{dst_name}")
        elif dst.exists():
            print(f"skip existing synthetic/{dst_name}")
        else:
            print(f"WARN: source missing {src}")

    # 2. 跑一次扫描（自动发现）
    engine = await make_engine(f"sqlite+aiosqlite:///{Path(cfg.data_dir) / 'app.db'}")
    sm = await make_sessionmaker(engine)
    await ensure_schema_and_admin(engine, sm)
    result = await scan_luts(sm, luts_dir)
    print(f"scan: discovered={len(result.discovered)} skipped={len(result.skipped_existing)}")

    # 3. 把 synthetic/* 的 enabled 改为 1（首次种子时打开）
    from sqlalchemy import select, update  # noqa: F401
    from myphoto.models import Lut  # noqa: F401
    async with sm() as s:
        for slug in ["warm", "cool", "mono"]:
            row = (await s.execute(select(Lut).where(Lut.slug == slug))).scalar_one_or_none()
            if row:
                row.enabled = 1
                if not row.label or row.label == row.slug:
                    row.label = next(lbl for src, fn, lbl in SYNTHETIC_PRESETS if fn.startswith(slug))
        await s.commit()
    await engine.dispose()
    print("done.")
    return 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
