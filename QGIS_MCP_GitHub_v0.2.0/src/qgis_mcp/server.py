"""建立供不同標準 MCP Client 使用的 QGIS MCP Server。"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server import MCPServer

from .audit import AuditLogger
from .bridge_client import BridgeClient
from .config import ServerSettings
from .constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PACKAGE_VERSION
from .errors import QgisMcpError
from .registry import InstanceRegistry
from .tool_service import ToolService


def _bounded_page_size(page_size: int) -> int:
    """限制單次圖徵筆數，避免模型上下文或 Bridge 記憶體被大量資料耗盡。"""
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise QgisMcpError(
            "INVALID_PARAMETERS",
            f"page_size 必須介於 1 與 {MAX_PAGE_SIZE} 之間。",
        )
    return page_size


def create_server(settings: ServerSettings | None = None) -> MCPServer:
    """依目前環境建立一個無供應商綁定的 MCP Server。"""
    active_settings = settings or ServerSettings.from_env()
    registry = InstanceRegistry(active_settings.registry_dir, active_settings.registry_ttl_seconds)
    bridge = BridgeClient(registry, active_settings.bridge_timeout_seconds)
    audit = AuditLogger(active_settings.log_dir, active_settings.log_retention_days)
    service = ToolService(registry, bridge, audit)
    mcp = MCPServer(
        "QGIS MCP",
        version=PACKAGE_VERSION,
        instructions=(
            "先呼叫 list_qgis_instances，再把明確的 instance_id 傳給所有 QGIS 工具。"
            "修改或覆寫資料的操作會在 QGIS 視窗要求真人確認。"
            "大量圖徵請使用分頁或匯出檔案，不要要求無限制回傳。"
        ),
    )

    @mcp.tool()
    async def list_qgis_instances(include_offline: bool = False) -> dict[str, Any]:
        """列出已啟用 QGIS MCP Bridge 的 QGIS Desktop 實例；不回傳任何 token。"""
        return service.list_instances(include_offline=include_offline)

    @mcp.tool()
    async def get_qgis_status(instance_id: str) -> dict[str, Any]:
        """取得指定 QGIS 實例、Bridge、Qt、Python、GDAL 與專案狀態。"""
        return await service.call(instance_id, "get_qgis_status")

    @mcp.tool()
    async def get_project_info(instance_id: str) -> dict[str, Any]:
        """取得指定 QGIS 專案的名稱、路徑、CRS、圖層數與未儲存狀態。"""
        return await service.call(instance_id, "get_project_info")

    @mcp.tool()
    async def save_project(instance_id: str) -> dict[str, Any]:
        """在 QGIS GUI 確認後儲存目前專案；未命名專案應改用 save_project_as。"""
        return await service.call(instance_id, "save_project")

    @mcp.tool()
    async def save_project_as(instance_id: str, output_path: str) -> dict[str, Any]:
        """在 QGIS GUI 確認完整路徑後，將目前專案另存為指定 QGZ/QGS。"""
        return await service.call(instance_id, "save_project_as", {"output_path": output_path})

    @mcp.tool()
    async def list_layers(
        instance_id: str,
        layer_type: Literal["all", "vector", "raster"] = "all",
    ) -> dict[str, Any]:
        """列出專案圖層；後續操作請使用回傳的穩定 layer_id。"""
        return await service.call(instance_id, "list_layers", {"layer_type": layer_type})

    @mcp.tool()
    async def get_layer_info(instance_id: str, layer_id: str) -> dict[str, Any]:
        """取得單一圖層的資料來源、CRS、範圍、欄位或 Raster 摘要。"""
        return await service.call(instance_id, "get_layer_info", {"layer_id": layer_id})

    @mcp.tool()
    async def get_raster_info(instance_id: str, layer_id: str) -> dict[str, Any]:
        """取得本機 Raster 網格、各 band 型別、NoData、scale、offset 與 metadata。"""
        return await service.call(instance_id, "get_raster_info", {"layer_id": layer_id})

    @mcp.tool()
    async def prepare_raster(
        instance_id: str,
        layer_id: str,
        reference_layer_id: str,
        output_path: str,
        bbox: list[float] | None = None,
        resampling: Literal["nearest", "bilinear", "cubic", "lanczos", "average", "mode"] = "bilinear",
        output_nodata: float | None = None,
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """裁切 Raster 並精確對齊參考 Raster 網格；bbox 使用參考 Raster CRS。"""
        return await service.call(
            instance_id,
            "prepare_raster",
            {
                "layer_id": layer_id,
                "reference_layer_id": reference_layer_id,
                "output_path": output_path,
                "bbox": bbox,
                "resampling": resampling,
                "output_nodata": output_nodata,
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def reproject_raster(
        instance_id: str,
        layer_id: str,
        output_path: str,
        target_crs: str,
        target_resolution: float,
        bbox: list[float] | None = None,
        resampling: Literal["nearest", "bilinear", "cubic", "lanczos", "average", "mode"] = "bilinear",
        output_nodata: float | None = None,
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """以明確 CRS、解析度、重採樣與 NoData 建立新的 COG Raster。"""
        return await service.call(
            instance_id,
            "reproject_raster",
            {
                "layer_id": layer_id,
                "output_path": output_path,
                "target_crs": target_crs,
                "target_resolution": target_resolution,
                "bbox": bbox,
                "resampling": resampling,
                "output_nodata": output_nodata,
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def calculate_ndvi(
        instance_id: str,
        red_layer_id: str,
        red_band: int,
        nir_layer_id: str,
        nir_band: int,
        output_path: str,
        calibration_mode: Literal["reflectance", "metadata", "explicit"] = "reflectance",
        red_scale: float | None = None,
        red_offset: float | None = None,
        nir_scale: float | None = None,
        nir_offset: float | None = None,
        mask_layer_id: str = "",
        mask_band: int = 1,
        mask_valid_values: list[float] | None = None,
        output_nodata: float = -9999.0,
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """計算 Float32 NDVI；不猜測 Red/NIR、校正或品質遮罩。"""
        return await service.call(
            instance_id,
            "calculate_ndvi",
            {
                "red_layer_id": red_layer_id,
                "red_band": red_band,
                "nir_layer_id": nir_layer_id,
                "nir_band": nir_band,
                "output_path": output_path,
                "calibration_mode": calibration_mode,
                "red_scale": red_scale,
                "red_offset": red_offset,
                "nir_scale": nir_scale,
                "nir_offset": nir_offset,
                "mask_layer_id": mask_layer_id,
                "mask_band": mask_band,
                "mask_valid_values": mask_valid_values or [],
                "output_nodata": output_nodata,
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def analyze_raster_colors(
        instance_id: str,
        layer_id: str,
        band_numbers: list[int] | None = None,
        histogram_bins: int = 32,
        sample_size: int = 250_000,
    ) -> dict[str, Any]:
        """抽樣原始 band 值並回傳有效像元比例、分位數與直方圖；不回傳完整像元。"""
        return await service.call(
            instance_id,
            "analyze_raster_colors",
            {
                "layer_id": layer_id,
                "band_numbers": band_numbers or [],
                "histogram_bins": histogram_bins,
                "sample_size": sample_size,
            },
        )

    @mcp.tool()
    async def apply_raster_style(
        instance_id: str,
        layer_id: str,
        mode: Literal["rgb", "grayscale", "pseudocolor"],
        red_band: int = 1,
        green_band: int = 2,
        blue_band: int = 3,
        band: int = 1,
        classes: list[dict[str, Any]] | None = None,
        interpolation: Literal["linear", "discrete", "exact"] = "linear",
    ) -> dict[str, Any]:
        """套用 RGB、灰階或使用明確色階的單波段樣式；NoData 維持透明。"""
        return await service.call(
            instance_id,
            "apply_raster_style",
            {
                "layer_id": layer_id,
                "mode": mode,
                "red_band": red_band,
                "green_band": green_band,
                "blue_band": blue_band,
                "band": band,
                "classes": classes or [],
                "interpolation": interpolation,
            },
        )

    @mcp.tool()
    async def run_zonal_statistics(
        instance_id: str,
        raster_layer_id: str,
        zones_layer_id: str,
        output_path: str,
        raster_band: int = 1,
        column_prefix: str = "ndvi_",
        statistics: list[
            Literal[
                "count",
                "sum",
                "mean",
                "median",
                "stdev",
                "minimum",
                "maximum",
                "range",
                "minority",
                "majority",
                "variety",
                "variance",
            ]
        ] | None = None,
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """以多邊形計算完整 Raster 像元統計，原子輸出新的 GeoPackage。"""
        return await service.call(
            instance_id,
            "run_zonal_statistics",
            {
                "raster_layer_id": raster_layer_id,
                "zones_layer_id": zones_layer_id,
                "output_path": output_path,
                "raster_band": raster_band,
                "column_prefix": column_prefix,
                "statistics": statistics or ["count", "mean", "minimum", "maximum"],
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def convert_raster_format(
        instance_id: str,
        layer_id: str,
        output_path: str,
        output_format: Literal["COG", "GTiff"] = "COG",
        compression: Literal["DEFLATE", "LZW", "ZSTD", "NONE"] = "DEFLATE",
        block_size: int = 512,
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """輸出 GeoTIFF／COG 及同名 JSON manifest；覆寫需 QGIS GUI 確認。"""
        return await service.call(
            instance_id,
            "convert_raster_format",
            {
                "layer_id": layer_id,
                "output_path": output_path,
                "output_format": output_format,
                "compression": compression,
                "block_size": block_size,
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def add_layer(
        instance_id: str,
        source: str,
        name: str = "",
        provider: str = "",
        layer_kind: Literal["auto", "vector", "raster"] = "auto",
    ) -> dict[str, Any]:
        """將本機檔案、WMS/WFS URI 或其他 QGIS 資料來源加入專案。"""
        return await service.call(
            instance_id,
            "add_layer",
            {"source": source, "name": name, "provider": provider, "layer_kind": layer_kind},
        )

    @mcp.tool()
    async def remove_layer(instance_id: str, layer_id: str) -> dict[str, Any]:
        """在 QGIS GUI 確認後從專案移除圖層；不直接刪除來源檔案。"""
        return await service.call(instance_id, "remove_layer", {"layer_id": layer_id})

    @mcp.tool()
    async def set_layer_visibility(instance_id: str, layer_id: str, visible: bool) -> dict[str, Any]:
        """切換指定圖層在目前圖層樹與地圖畫布的可見狀態。"""
        return await service.call(
            instance_id,
            "set_layer_visibility",
            {"layer_id": layer_id, "visible": visible},
        )

    @mcp.tool()
    async def reorder_layers(instance_id: str, ordered_layer_ids: list[str]) -> dict[str, Any]:
        """依由上至下的 layer_id 清單調整根圖層群組順序。"""
        return await service.call(
            instance_id,
            "reorder_layers",
            {"ordered_layer_ids": ordered_layer_ids},
        )

    @mcp.tool()
    async def rename_layer(instance_id: str, layer_id: str, new_name: str) -> dict[str, Any]:
        """修改 QGIS 專案中的圖層顯示名稱，不改來源檔名。"""
        return await service.call(
            instance_id,
            "rename_layer",
            {"layer_id": layer_id, "new_name": new_name},
        )

    @mcp.tool()
    async def export_layer(
        instance_id: str,
        layer_id: str,
        output_path: str,
        output_crs: str = "",
        only_selected: bool = False,
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """匯出向量或 Raster 圖層；覆寫既有路徑時由 QGIS GUI 確認。"""
        return await service.call(
            instance_id,
            "export_layer",
            {
                "layer_id": layer_id,
                "output_path": output_path,
                "output_crs": output_crs,
                "only_selected": only_selected,
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def list_fields(instance_id: str, layer_id: str) -> dict[str, Any]:
        """列出向量圖層欄位名稱、型別、長度、精度與限制。"""
        return await service.call(instance_id, "list_fields", {"layer_id": layer_id})

    @mcp.tool()
    async def validate_expression(instance_id: str, layer_id: str, expression: str) -> dict[str, Any]:
        """只解析 QGIS Expression 並回報錯誤與參照欄位，不修改任何資料。"""
        return await service.call(
            instance_id,
            "validate_expression",
            {"layer_id": layer_id, "expression": expression},
        )

    @mcp.tool()
    async def add_fields(instance_id: str, layer_id: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
        """在 QGIS GUI 確認後新增欄位；每筆需含 name、type，可含 length、precision。"""
        return await service.call(instance_id, "add_fields", {"layer_id": layer_id, "fields": fields})

    @mcp.tool()
    async def calculate_field(
        instance_id: str,
        layer_id: str,
        field_name: str,
        expression: str,
        only_selected: bool = False,
    ) -> dict[str, Any]:
        """先驗證 QGIS Expression，再經 GUI 確認批次更新目標欄位。"""
        return await service.call(
            instance_id,
            "calculate_field",
            {
                "layer_id": layer_id,
                "field_name": field_name,
                "expression": expression,
                "only_selected": only_selected,
            },
        )

    @mcp.tool()
    async def delete_fields(instance_id: str, layer_id: str, field_names: list[str]) -> dict[str, Any]:
        """在 QGIS GUI 確認後刪除欄位；此操作可能無法由資料提供者復原。"""
        return await service.call(
            instance_id,
            "delete_fields",
            {"layer_id": layer_id, "field_names": field_names},
        )

    @mcp.tool()
    async def select_features(
        instance_id: str,
        layer_id: str,
        expression: str = "",
        bbox: list[float] | None = None,
        mode: Literal["replace", "add", "remove", "intersect"] = "replace",
    ) -> dict[str, Any]:
        """依 QGIS Expression、bbox 或兩者交集選取圖徵。"""
        return await service.call(
            instance_id,
            "select_features",
            {"layer_id": layer_id, "expression": expression, "bbox": bbox, "mode": mode},
        )

    @mcp.tool()
    async def clear_selection(instance_id: str, layer_id: str) -> dict[str, Any]:
        """清除指定向量圖層的目前選取。"""
        return await service.call(instance_id, "clear_selection", {"layer_id": layer_id})

    @mcp.tool()
    async def get_selected_features(
        instance_id: str,
        layer_id: str,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        geometry_format: Literal["none", "summary", "wkt", "geojson"] = "none",
    ) -> dict[str, Any]:
        """分頁取得選取圖徵的完整屬性；完整 geometry 必須明確指定。"""
        try:
            safe_page_size = _bounded_page_size(page_size)
        except QgisMcpError as error:
            return ToolService._error_response(instance_id, error)
        return await service.call(
            instance_id,
            "get_selected_features",
            {
                "layer_id": layer_id,
                "page": page,
                "page_size": safe_page_size,
                "geometry_format": geometry_format,
            },
        )

    @mcp.tool()
    async def query_features(
        instance_id: str,
        layer_id: str,
        expression: str = "",
        bbox: list[float] | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        geometry_format: Literal["none", "summary", "wkt", "geojson"] = "none",
        order_by: str = "",
    ) -> dict[str, Any]:
        """依條件分頁查詢圖徵，不變更 QGIS 選取；大量結果應改用匯出。"""
        try:
            safe_page_size = _bounded_page_size(page_size)
        except QgisMcpError as error:
            return ToolService._error_response(instance_id, error)
        return await service.call(
            instance_id,
            "query_features",
            {
                "layer_id": layer_id,
                "expression": expression,
                "bbox": bbox,
                "page": page,
                "page_size": safe_page_size,
                "geometry_format": geometry_format,
                "order_by": order_by,
            },
        )

    @mcp.tool()
    async def export_feature_query(
        instance_id: str,
        layer_id: str,
        output_path: str,
        expression: str = "",
        bbox: list[float] | None = None,
        output_format: Literal["json", "geojson"] = "geojson",
    ) -> dict[str, Any]:
        """將大量查詢結果輸出成 JSON/GeoJSON，只把路徑與摘要送回 MCP Client。"""
        return await service.call(
            instance_id,
            "export_feature_query",
            {
                "layer_id": layer_id,
                "output_path": output_path,
                "expression": expression,
                "bbox": bbox,
                "output_format": output_format,
            },
        )

    @mcp.tool()
    async def zoom_to_features(instance_id: str, layer_id: str, selected_only: bool = True) -> dict[str, Any]:
        """將 QGIS 畫布縮放至選取圖徵或整個圖層。"""
        return await service.call(
            instance_id,
            "zoom_to_features",
            {"layer_id": layer_id, "selected_only": selected_only},
        )

    @mcp.tool()
    async def list_processing_providers(instance_id: str) -> dict[str, Any]:
        """列出目前 QGIS 實例已啟用的全部 Processing providers。"""
        return await service.call(instance_id, "list_processing_providers")

    @mcp.tool()
    async def search_processing_algorithms(
        instance_id: str,
        query: str = "",
        provider_id: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """依 ID、名稱或群組搜尋目前已註冊的 Processing 演算法。"""
        return await service.call(
            instance_id,
            "search_processing_algorithms",
            {"query": query, "provider_id": provider_id, "limit": limit},
        )

    @mcp.tool()
    async def get_processing_algorithm_help(instance_id: str, algorithm_id: str) -> dict[str, Any]:
        """取得 Processing 演算法參數、輸出、flags 與說明，再據此建立正確呼叫。"""
        return await service.call(
            instance_id,
            "get_processing_algorithm_help",
            {"algorithm_id": algorithm_id},
        )

    @mcp.tool()
    async def run_processing_algorithm(
        instance_id: str,
        algorithm_id: str,
        parameters: dict[str, Any],
        add_outputs_to_project: bool = True,
    ) -> dict[str, Any]:
        """非同步執行任一已安裝 Processing 演算法；有副作用時 QGIS 會要求確認。"""
        return await service.call(
            instance_id,
            "run_processing_algorithm",
            {
                "algorithm_id": algorithm_id,
                "parameters": parameters,
                "add_outputs_to_project": add_outputs_to_project,
            },
        )

    @mcp.tool()
    async def get_job_status(instance_id: str, job_id: str) -> dict[str, Any]:
        """取得長時間 QGIS 工作的狀態、進度、階段與訊息。"""
        return await service.call(instance_id, "get_job_status", {"job_id": job_id})

    @mcp.tool()
    async def get_job_result(instance_id: str, job_id: str) -> dict[str, Any]:
        """取得已完成工作的結構化結果；未完成時回傳目前狀態。"""
        return await service.call(instance_id, "get_job_result", {"job_id": job_id})

    @mcp.tool()
    async def cancel_job(instance_id: str, job_id: str) -> dict[str, Any]:
        """要求取消工作；底層不支援即時取消時會明確回報。"""
        return await service.call(instance_id, "cancel_job", {"job_id": job_id})

    @mcp.tool()
    async def get_layer_style_info(instance_id: str, layer_id: str) -> dict[str, Any]:
        """取得圖層 renderer 類型、分類欄位、標籤與常用樣式摘要。"""
        return await service.call(instance_id, "get_layer_style_info", {"layer_id": layer_id})

    @mcp.tool()
    async def apply_single_style(
        instance_id: str,
        layer_id: str,
        fill_color: str,
        outline_color: str = "#000000",
        opacity: float = 1.0,
        size: float = 2.0,
    ) -> dict[str, Any]:
        """套用單一符號樣式；顏色接受 #RRGGBB 或 #RRGGBBAA。"""
        return await service.call(
            instance_id,
            "apply_single_style",
            {
                "layer_id": layer_id,
                "fill_color": fill_color,
                "outline_color": outline_color,
                "opacity": opacity,
                "size": size,
            },
        )

    @mcp.tool()
    async def apply_categorized_style(
        instance_id: str,
        layer_id: str,
        field_name: str,
        categories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """依欄位套用分類樣式；每筆 category 需含 value 與 color，可含 label。"""
        return await service.call(
            instance_id,
            "apply_categorized_style",
            {"layer_id": layer_id, "field_name": field_name, "categories": categories},
        )

    @mcp.tool()
    async def apply_graduated_style(
        instance_id: str,
        layer_id: str,
        field_name: str,
        classes: int = 5,
        mode: Literal["equal_interval", "quantile", "jenks", "stddev", "pretty"] = "equal_interval",
        color_ramp: str = "Viridis",
    ) -> dict[str, Any]:
        """依數值欄位套用漸層分級樣式。"""
        return await service.call(
            instance_id,
            "apply_graduated_style",
            {
                "layer_id": layer_id,
                "field_name": field_name,
                "classes": classes,
                "mode": mode,
                "color_ramp": color_ramp,
            },
        )

    @mcp.tool()
    async def apply_rgb_field_style(
        instance_id: str,
        layer_id: str,
        red_field: str = "R",
        green_field: str = "G",
        blue_field: str = "B",
    ) -> dict[str, Any]:
        """以三個 0–255 欄位的 data-defined expression 驅動圖徵色彩。"""
        return await service.call(
            instance_id,
            "apply_rgb_field_style",
            {
                "layer_id": layer_id,
                "red_field": red_field,
                "green_field": green_field,
                "blue_field": blue_field,
            },
        )

    @mcp.tool()
    async def preview_color_mapping(
        instance_id: str,
        layer_id: str,
        category_field: str,
        mapping_path: str,
        mapping_key_field: str,
    ) -> dict[str, Any]:
        """預覽 CSV/JSON 色碼表配對結果，不修改圖層。"""
        return await service.call(
            instance_id,
            "preview_color_mapping",
            {
                "layer_id": layer_id,
                "category_field": category_field,
                "mapping_path": mapping_path,
                "mapping_key_field": mapping_key_field,
            },
        )

    @mcp.tool()
    async def apply_color_mapping(
        instance_id: str,
        layer_id: str,
        category_field: str,
        mapping_path: str,
        mapping_key_field: str,
        red_field: str = "R",
        green_field: str = "G",
        blue_field: str = "B",
    ) -> dict[str, Any]:
        """經 GUI 確認後由 CSV/JSON 色碼表寫入 R/G/B 欄位並套用樣式。"""
        return await service.call(
            instance_id,
            "apply_color_mapping",
            {
                "layer_id": layer_id,
                "category_field": category_field,
                "mapping_path": mapping_path,
                "mapping_key_field": mapping_key_field,
                "red_field": red_field,
                "green_field": green_field,
                "blue_field": blue_field,
            },
        )

    @mcp.tool()
    async def import_qml_style(instance_id: str, layer_id: str, qml_path: str) -> dict[str, Any]:
        """將本機 QML 樣式載入指定圖層。"""
        return await service.call(
            instance_id,
            "import_qml_style",
            {"layer_id": layer_id, "qml_path": qml_path},
        )

    @mcp.tool()
    async def export_qml_style(instance_id: str, layer_id: str, output_path: str) -> dict[str, Any]:
        """匯出圖層 QML；覆寫既有檔案時由 QGIS GUI 確認。"""
        return await service.call(
            instance_id,
            "export_qml_style",
            {"layer_id": layer_id, "output_path": output_path},
        )

    @mcp.tool()
    async def inspect_tabular_coordinates(
        instance_id: str,
        input_path: str,
        sample_size: int = 20,
    ) -> dict[str, Any]:
        """檢查 CSV/JSON 欄位與座標候選；CRS 推測只作提示，不能直接當作事實。"""
        return await service.call(
            instance_id,
            "inspect_tabular_coordinates",
            {"input_path": input_path, "sample_size": sample_size},
        )

    @mcp.tool()
    async def table_to_vector(
        instance_id: str,
        input_path: str,
        output_path: str,
        x_field: str,
        y_field: str,
        source_crs: str,
        output_crs: str = "",
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """把明確指定 X/Y 與來源 CRS 的 CSV/JSON 轉為 SHP/GPKG/GeoJSON 點圖層。"""
        return await service.call(
            instance_id,
            "table_to_vector",
            {
                "input_path": input_path,
                "output_path": output_path,
                "x_field": x_field,
                "y_field": y_field,
                "source_crs": source_crs,
                "output_crs": output_crs,
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def convert_vector_format(
        instance_id: str,
        layer_id: str,
        output_path: str,
        output_crs: str = "",
        only_selected: bool = False,
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """將向量圖層轉為由副檔名決定的 SHP、GPKG、GeoJSON 等格式。"""
        return await service.call(
            instance_id,
            "convert_vector_format",
            {
                "layer_id": layer_id,
                "output_path": output_path,
                "output_crs": output_crs,
                "only_selected": only_selected,
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def check_geometry_validity(
        instance_id: str,
        layer_id: str,
        selected_only: bool = False,
        create_error_layer: bool = True,
    ) -> dict[str, Any]:
        """檢查空幾何與無效幾何，並可建立錯誤點/圖徵記憶體圖層。"""
        return await service.call(
            instance_id,
            "check_geometry_validity",
            {
                "layer_id": layer_id,
                "selected_only": selected_only,
                "create_error_layer": create_error_layer,
            },
        )

    @mcp.tool()
    async def check_polygon_closedness(
        instance_id: str,
        layer_id: str,
        selected_only: bool = False,
    ) -> dict[str, Any]:
        """檢查面圖層環的封閉性與可用性，回傳問題 feature IDs。"""
        return await service.call(
            instance_id,
            "check_polygon_closedness",
            {"layer_id": layer_id, "selected_only": selected_only},
        )

    @mcp.tool()
    async def fix_geometries(
        instance_id: str,
        layer_id: str,
        output_path: str = "TEMPORARY_OUTPUT",
        modify_original: bool = False,
        add_to_project: bool = True,
    ) -> dict[str, Any]:
        """修復幾何；預設建立新圖層，修改原始圖層時一定要求 GUI 確認。"""
        return await service.call(
            instance_id,
            "fix_geometries",
            {
                "layer_id": layer_id,
                "output_path": output_path,
                "modify_original": modify_original,
                "add_to_project": add_to_project,
            },
        )

    @mcp.tool()
    async def get_canvas_state(instance_id: str) -> dict[str, Any]:
        """取得目前畫布 CRS、範圍、像素尺寸、比例尺與可見圖層。"""
        return await service.call(instance_id, "get_canvas_state")

    @mcp.tool()
    async def set_canvas_extent(instance_id: str, bbox: list[float], crs: str = "") -> dict[str, Any]:
        """將畫布移至 [xmin, ymin, xmax, ymax]；crs 留空代表畫布 CRS。"""
        return await service.call(
            instance_id,
            "set_canvas_extent",
            {"bbox": bbox, "crs": crs},
        )

    @mcp.tool()
    async def zoom_to_layer(instance_id: str, layer_id: str) -> dict[str, Any]:
        """將目前 QGIS 畫布縮放至指定圖層範圍。"""
        return await service.call(instance_id, "zoom_to_layer", {"layer_id": layer_id})

    @mcp.tool()
    async def capture_canvas(
        instance_id: str,
        output_path: str,
        width: int = 0,
        height: int = 0,
    ) -> dict[str, Any]:
        """將目前地圖畫布輸出成 PNG；覆寫既有檔案時要求 GUI 確認。"""
        return await service.call(
            instance_id,
            "capture_canvas",
            {"output_path": output_path, "width": width, "height": height},
        )

    return mcp
