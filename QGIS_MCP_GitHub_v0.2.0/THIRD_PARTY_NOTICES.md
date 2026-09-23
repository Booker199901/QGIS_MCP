# Third-party notices

QGIS MCP Server 0.2.0 的 Windows bundle 使用 Python 3.13，並包含下列主要直接與遞移相依套件。版本以本次正式建置環境為準；各套件的完整授權文字與著作權聲明仍以 bundle 內的套件 metadata／license files 及上游發行內容為準。

| 套件 | 版本 | 授權識別／家族 |
|---|---:|---|
| Python | 3.13 | PSF License |
| mcp | 2.0.0 | MIT |
| mcp-types | 2.0.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| httpx2 | 2.10.0 | BSD family |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpcore2 | 2.10.0 | BSD family |
| pydantic | 2.13.4 | MIT |
| pydantic-core | 2.46.4 | MIT |
| platformdirs | 4.11.2 | MIT |
| uvicorn | 0.52.1 | BSD-3-Clause |
| starlette | 1.6.0 | BSD-3-Clause |
| sse-starlette | 3.4.8 | BSD-3-Clause |
| anyio | 4.14.2 | MIT |
| attrs | 26.1.0 | MIT |
| annotated-types | 0.8.0 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| cffi | 2.1.1 | MIT |
| click | 8.4.2 | BSD-3-Clause |
| colorama | 0.4.6 | BSD-3-Clause |
| cryptography | 50.0.0 | Apache-2.0 OR BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| idna | 3.18 | BSD-3-Clause |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| opentelemetry-api | 1.44.0 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pycparser | 3.0 | BSD-3-Clause |
| PyJWT | 2.13.0 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| pywin32 | 312 | PSF License |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.6.3 | MIT |
| truststore | 0.10.4 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |

QGIS 與 PyQGIS 不會被打包進 MCP Server。QGIS Bridge Plugin 在使用者既有的 QGIS 安裝內執行，並依本專案的 GPL-2.0-or-later 條款散布。
