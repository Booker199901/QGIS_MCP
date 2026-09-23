"""將 PyInstaller onedir 與必要文件封裝成 Windows 使用者 ZIP。"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 固定以腳本位置解析專案根目錄。
INPUT_DIR = PROJECT_ROOT / "build" / "release" / "windows" / "qgis-mcp-0.2.0"
OUTPUT_DIR = PROJECT_ROOT / "build" / "release"
OUTPUT_PATH = OUTPUT_DIR / "qgis-mcp-server-windows-x64-0.2.0.zip"
WHEEL_PATH = OUTPUT_DIR / "python" / "qgis_mcp-0.2.0-py3-none-any.whl"
DOCUMENTS = [
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "DEVELOPMENT_REQUIREMENTS.md",
    PROJECT_ROOT / "LICENSE",
    PROJECT_ROOT / "THIRD_PARTY_NOTICES.md",
    PROJECT_ROOT / "docs" / "SECURITY.md",
    PROJECT_ROOT / "docs" / "TESTING.md",
    PROJECT_ROOT / "docs" / "V1_IMPLEMENTATION.md",
    PROJECT_ROOT / "docs" / "V1_1_IMPLEMENTATION.md",
    PROJECT_ROOT / "examples" / "generic_stdio.json",
    PROJECT_ROOT / "examples" / "generic_streamable_http.json",
]
ARCHIVE_ROOT = "qgis-mcp-server-windows-x64-0.2.0"


def main() -> int:
    """驗證 exe 後封裝完整資料夾，並建立 SHA-256 sidecar。"""
    executable = INPUT_DIR / "qgis-mcp-0.2.0.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"找不到 PyInstaller 執行檔：{executable}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(INPUT_DIR.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                relative = path.relative_to(INPUT_DIR).as_posix()
                archive.write(path, f"{ARCHIVE_ROOT}/{relative}")
        for document in DOCUMENTS:
            archive.write(document, f"{ARCHIVE_ROOT}/{document.name}")
    digest = hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest()
    OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".sha256").write_text(
        f"{digest}  {OUTPUT_PATH.name}\n", encoding="ascii"
    )
    if WHEEL_PATH.is_file():
        wheel_digest = hashlib.sha256(WHEEL_PATH.read_bytes()).hexdigest()
        WHEEL_PATH.with_suffix(WHEEL_PATH.suffix + ".sha256").write_text(
            f"{wheel_digest}  {WHEEL_PATH.name}\n", encoding="ascii"
        )
    print(f"Windows bundle：{OUTPUT_PATH}")
    print(f"SHA-256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
