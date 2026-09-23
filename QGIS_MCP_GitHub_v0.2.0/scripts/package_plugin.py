"""建立可由 QGIS Plugin Manager 安裝的可重現 ZIP。"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 由腳本路徑取得工作區，不依賴目前目錄。
INPUT_DIR = PROJECT_ROOT / "qgis_plugin" / "qgis_mcp_bridge"  # 唯一允許打包的外掛來源。
OUTPUT_DIR = PROJECT_ROOT / "build" / "release"  # 所有發行產物集中於 build。
OUTPUT_PATH = OUTPUT_DIR / "qgis_mcp_bridge-0.2.0.zip"  # 版本需與 metadata.txt 一致。
ARCHIVE_ROOT = "qgis_mcp_bridge"  # QGIS ZIP 最上層必須是外掛資料夾。
REQUIRED_FILES = {"__init__.py", "metadata.txt", "LICENSE"}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache"}


def _source_files() -> list[Path]:
    """收集固定排序來源，拒絕缺少 QGIS 外掛必要檔。"""
    missing = [name for name in sorted(REQUIRED_FILES) if not (INPUT_DIR / name).is_file()]
    if missing:
        raise FileNotFoundError(f"外掛缺少必要檔案：{', '.join(missing)}")
    return [
        path
        for path in sorted(INPUT_DIR.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
        and not any(part in EXCLUDED_PARTS for part in path.parts)
        and path.suffix.lower() not in {".pyc", ".pyo"}
    ]


def _zip_info(archive_name: str) -> zipfile.ZipInfo:
    """固定時間與權限，讓相同來源產生相同 ZIP checksum。"""
    info = zipfile.ZipInfo(archive_name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def main() -> int:
    """驗證來源後建立 ZIP，並輸出 SHA-256 供安裝包核對。"""
    files = _source_files()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT_PATH, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(INPUT_DIR).as_posix()
            archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/{relative}"), path.read_bytes())
    digest = hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest()
    checksum_path = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {OUTPUT_PATH.name}\n", encoding="ascii")
    print(f"已封裝 {len(files)} 個檔案：{OUTPUT_PATH}")
    print(f"SHA-256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
