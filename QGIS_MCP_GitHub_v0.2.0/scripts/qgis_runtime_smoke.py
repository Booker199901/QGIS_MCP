"""在真實 QGIS Python runtime 中驗證 V1 核心操作，不讀寫使用者 GIS 資料。"""

from __future__ import annotations

import http.client
import json
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
from osgeo import gdal, osr
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 由腳本位置解析專案根目錄。
INPUT_DIR = PROJECT_ROOT / "tests"  # 此 smoke test 只使用程式建立的記憶體資料。
OUTPUT_DIR = PROJECT_ROOT / "build" / "qgis-smoke"  # 測試報告集中放在可清除的 build 目錄。
PLUGIN_ROOT = PROJECT_ROOT / "qgis_plugin"  # 直接測試目前工作區的外掛來源。


class AcceptConfirmation:
    """僅在隔離的測試記憶體圖層中自動核准，正式外掛不會使用此類別。"""

    def __init__(self) -> None:
        self.requests: list[str] = []  # 保存確認名稱，驗證危險操作確實有走確認流程。

    def require(self, operation_name: str, _summary: str, _details: str) -> None:
        """記錄已要求確認；測試資料不屬於使用者，因此不顯示 GUI。"""
        self.requests.append(operation_name)


class MockCanvas:
    """為不涉及真實畫布的樣式操作提供最小 refresh 介面。"""

    def refresh(self) -> None:
        """樣式 smoke test 不需實際繪製。"""


class MockLayerTreeView:
    """提供 refreshLayerSymbology 的最小測試替身。"""

    def refreshLayerSymbology(self, _layer_id: str) -> None:  # noqa: N802 - 對齊 QGIS API。
        """不建立 GUI，僅確認方法可被呼叫。"""


class MockIface:
    """提供核心非 GUI operations 需要的有限 QGIS iface methods。"""

    def __init__(self) -> None:
        self._canvas = MockCanvas()
        self._tree = MockLayerTreeView()

    def mapCanvas(self) -> MockCanvas:  # noqa: N802 - 對齊 QGIS API。
        """回傳不繪圖的測試畫布。"""
        return self._canvas

    def layerTreeView(self) -> MockLayerTreeView:  # noqa: N802 - 對齊 QGIS API。
        """回傳不建立 widget 的圖層樹替身。"""
        return self._tree


def _meta_type(name: str):
    """取得 Qt5/Qt6 共通 QMetaType enum。"""
    meta_types = getattr(QMetaType, "Type", QMetaType)
    return getattr(meta_types, name)


def _create_test_layer() -> QgsVectorLayer:
    """建立三筆點圖徵，供欄位、查詢、樣式與 buffer 測試。"""
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "qgis_mcp_smoke", "memory")
    if not layer.isValid():
        raise RuntimeError("Failed to create memory layer")
    fields = [
        QgsField("name", _meta_type("QString")),
        QgsField("value", _meta_type("Double")),
        QgsField("result", _meta_type("Double")),
        QgsField("category", _meta_type("QString")),
    ]
    if not layer.dataProvider().addAttributes(fields):
        raise RuntimeError("Failed to add smoke-test fields")
    layer.updateFields()
    features = []
    for index, category in enumerate(["A", "B", "A"], start=1):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(120 + index / 100, 23 + index / 100)))
        feature.setAttributes([f"feature-{index}", float(index), None, category])
        features.append(feature)
    success, _created = layer.dataProvider().addFeatures(features)
    if not success:
        raise RuntimeError("Failed to add smoke-test features")
    layer.updateExtents()
    QgsProject.instance().addMapLayer(layer)
    return layer


def _create_test_raster(
    path: Path,
    name: str,
    values: np.ndarray,
    geotransform: list[float] | None = None,
    scale: float | None = None,
    offset: float | None = None,
) -> QgsRasterLayer:
    """建立具有明確 CRS、網格與 NoData 的小型 Float32 GeoTIFF。"""
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), 2, 2, 1, gdal.GDT_Float32)
    if dataset is None:
        raise RuntimeError("Failed to create smoke-test raster")
    dataset.SetGeoTransform(geotransform or [120.0, 0.01, 0.0, 24.0, 0.0, -0.01])
    spatial_reference = osr.SpatialReference()
    spatial_reference.ImportFromEPSG(4326)
    dataset.SetProjection(spatial_reference.ExportToWkt())
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    if scale is not None:
        band.SetScale(scale)
    if offset is not None:
        band.SetOffset(offset)
    band.WriteArray(values.astype(np.float32))
    band.FlushCache()
    dataset.FlushCache()
    dataset = None
    layer = QgsRasterLayer(str(path), name, "gdal")
    if not layer.isValid():
        raise RuntimeError("Failed to load smoke-test raster")
    QgsProject.instance().addMapLayer(layer)
    return layer


def _create_zone_layer() -> QgsVectorLayer:
    """建立覆蓋測試 Raster 的單一多邊形供分區統計使用。"""
    layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "ndvi_zone", "memory")
    if not layer.isValid():
        raise RuntimeError("Failed to create zonal-statistics layer")
    feature = QgsFeature(layer.fields())
    feature.setGeometry(
        QgsGeometry.fromWkt("POLYGON((120 23.98,120.02 23.98,120.02 24,120 24,120 23.98))")
    )
    if not layer.dataProvider().addFeature(feature):
        raise RuntimeError("Failed to add zonal-statistics feature")
    layer.updateExtents()
    QgsProject.instance().addMapLayer(layer)
    return layer


def _wait_for_job(app: QgsApplication, jobs, job_id: str, timeout_seconds: float = 30.0) -> dict:
    """處理 Qt events 直到工作完成或達到真實逾時。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        status = jobs.get_status(job_id)
        if status["status"] in {"completed", "failed", "cancelled"}:
            return status
        time.sleep(0.01)
    raise TimeoutError(f"QGIS job did not finish: {job_id}")


def _bridge_request(app: QgsApplication, port: int, token: str | None, request_id: str) -> dict:
    """由背景 thread 發 HTTP，主 thread 持續處理 QtNetwork events。"""
    result: dict[str, object] = {}

    def worker() -> None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {
            "Content-Type": "application/json",
            "X-QGIS-MCP-API-Version": "1",
        }
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps({"request_id": request_id, "action": "get_qgis_status", "params": {}})
        try:
            connection.request("POST", "/v1/command", body=body.encode("utf-8"), headers=headers)
            response = connection.getresponse()
            result["status"] = response.status
            result["body"] = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            result["error"] = error
        finally:
            connection.close()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while thread.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    thread.join(timeout=0.1)
    if thread.is_alive():
        raise TimeoutError("Bridge HTTP request did not finish")
    if "error" in result:
        raise RuntimeError("Bridge HTTP request failed") from result["error"]
    return result


def run_smoke() -> dict:
    """初始化 QGIS、執行核心操作並回傳版本化測試報告。"""
    sys.path.insert(0, str(PLUGIN_ROOT))
    from qgis.analysis import QgsNativeAlgorithms
    from qgis_mcp_bridge.errors import BridgeError
    from qgis_mcp_bridge.http_server import BridgeHttpServer
    from qgis_mcp_bridge.jobs import JobManager
    from qgis_mcp_bridge.operations import OperationHandler
    from qgis_mcp_bridge.router import CommandRouter
    from qgis_mcp_bridge.utils import redact_sensitive_text

    app = QgsApplication([], False)
    app.initQgis()
    native_provider = QgsNativeAlgorithms()
    if not QgsApplication.processingRegistry().addProvider(native_provider):
        raise RuntimeError("Failed to register QGIS Native Processing provider")
    confirmation = AcceptConfirmation()
    jobs = JobManager()
    operations = OperationHandler(MockIface(), confirmation, jobs)
    bridge_token = secrets.token_urlsafe(48)  # 測試用 token 只存在本次程序記憶體。
    bridge = BridgeHttpServer(CommandRouter("smoke-instance", operations), bridge_token)
    bridge.start()
    layer = _create_test_layer()
    runtime_dir = Path(tempfile.mkdtemp(prefix="qgis-mcp-smoke-"))
    red_layer = _create_test_raster(
        runtime_dir / "red.tif",
        "red",
        np.array([[0.2, 0.0], [0.1, -9999.0]]),
    )
    nir_layer = _create_test_raster(
        runtime_dir / "nir.tif",
        "nir",
        np.array([[0.6, 0.0], [0.5, 0.7]]),
    )
    mask_layer = _create_test_raster(
        runtime_dir / "mask.tif",
        "quality_mask",
        np.array([[1.0, 1.0], [0.0, 1.0]]),
    )
    shifted_layer = _create_test_raster(
        runtime_dir / "shifted.tif",
        "shifted",
        np.array([[0.6, 0.0], [0.5, 0.7]]),
        geotransform=[120.005, 0.01, 0.0, 24.0, 0.0, -0.01],
    )
    calibrated_layer = _create_test_raster(
        runtime_dir / "calibrated.tif",
        "calibrated",
        np.array([[2000.0, 3000.0], [4000.0, 5000.0]]),
        scale=0.0001,
        offset=-0.1,
    )
    zone_layer = _create_zone_layer()
    reprojected_layer = None
    zonal_layer = None
    mapping_path = runtime_dir / "colors.csv"
    mapping_path.write_text("zone,R,G,B\nA,255,0,0\nB,0,0,255\n", encoding="utf-8")

    report: dict[str, object] = {
        "qgis_version": operations.op_get_qgis_status({})["qgis_version"],
        "layer_id": layer.id(),
        "steps": {},
    }
    try:
        redacted = redact_sensitive_text(
            "host=localhost password='super-secret' authcfg=my-auth token=abc123"
        )
        report["steps"]["secret_redaction"] = "super-secret" not in redacted and "abc123" not in redacted
        print("SMOKE_STEP secret_redaction", flush=True)

        unauthenticated = _bridge_request(app, bridge.port, None, "smoke-request-unauthorized")
        authenticated = _bridge_request(app, bridge.port, bridge_token, "smoke-request-replay")
        replayed = _bridge_request(app, bridge.port, bridge_token, "smoke-request-replay")
        report["steps"]["bridge_http_security"] = (
            unauthenticated["status"] == 401
            and authenticated["status"] == 200
            and authenticated["body"]["success"] is True
            and replayed["body"]["error"]["code"] == "REQUEST_REPLAYED"
        )
        print("SMOKE_STEP bridge_http_security", flush=True)

        fields = operations.op_list_fields({"layer_id": layer.id()})
        report["steps"]["list_fields"] = fields["count"] == 4
        print("SMOKE_STEP list_fields", flush=True)

        expression = operations.op_validate_expression({"layer_id": layer.id(), "expression": '"value" * 2'})
        report["steps"]["validate_expression"] = expression["valid"]
        print("SMOKE_STEP validate_expression", flush=True)

        calculation = operations.op_calculate_field(
            {
                "layer_id": layer.id(),
                "field_name": "result",
                "expression": '"value" * 2',
                "only_selected": False,
            }
        )
        report["steps"]["calculate_field"] = calculation["updated_count"] == 3
        print("SMOKE_STEP calculate_field", flush=True)

        query = operations.op_query_features(
            {
                "layer_id": layer.id(),
                "expression": '"result" >= 4',
                "bbox": None,
                "page": 1,
                "page_size": 100,
                "geometry_format": "summary",
                "order_by": '"value"',
            }
        )
        report["steps"]["query_features"] = query["total_count"] == 2
        print("SMOKE_STEP query_features", flush=True)

        style = operations.op_apply_single_style(
            {
                "layer_id": layer.id(),
                "fill_color": "#44AA66",
                "outline_color": "#222222",
                "opacity": 0.8,
                "size": 3.0,
            }
        )
        report["steps"]["single_style"] = style["renderer_type"] == "singleSymbol"
        print("SMOKE_STEP single_style", flush=True)

        color_mapping = operations.op_apply_color_mapping(
            {
                "layer_id": layer.id(),
                "category_field": "category",
                "mapping_path": str(mapping_path),
                "mapping_key_field": "zone",
                "red_field": "R",
                "green_field": "G",
                "blue_field": "B",
            }
        )
        report["steps"]["color_mapping"] = color_mapping["updated_feature_count"] == 3
        print("SMOKE_STEP color_mapping", flush=True)

        validity = operations.op_check_geometry_validity(
            {"layer_id": layer.id(), "selected_only": False, "create_error_layer": False}
        )
        report["steps"]["geometry_validity"] = validity["issue_count"] == 0
        print("SMOKE_STEP geometry_validity", flush=True)

        raster_info = operations.op_get_raster_info({"layer_id": red_layer.id()})
        report["steps"]["raster_info"] = (
            raster_info["width"] == 2
            and raster_info["height"] == 2
            and raster_info["bands"][0]["nodata"] == -9999.0
        )
        print("SMOKE_STEP raster_info", flush=True)

        alignment_error = None
        try:
            operations.op_calculate_ndvi(
                {
                    "red_layer_id": red_layer.id(),
                    "red_band": 1,
                    "nir_layer_id": shifted_layer.id(),
                    "nir_band": 1,
                    "output_path": str(runtime_dir / "misaligned.tif"),
                    "calibration_mode": "reflectance",
                    "output_nodata": -9999.0,
                    "add_to_project": False,
                }
            )
        except BridgeError as error:
            alignment_error = error.code
        report["steps"]["raster_alignment_guard"] = alignment_error == "RASTER_ALIGNMENT_REQUIRED"
        print("SMOKE_STEP raster_alignment_guard", flush=True)

        calibration_error = None
        try:
            operations.op_calculate_ndvi(
                {
                    "red_layer_id": calibrated_layer.id(),
                    "red_band": 1,
                    "nir_layer_id": calibrated_layer.id(),
                    "nir_band": 1,
                    "output_path": str(runtime_dir / "calibration-conflict.tif"),
                    "calibration_mode": "explicit",
                    "red_scale": 1.0,
                    "red_offset": 0.0,
                    "nir_scale": 1.0,
                    "nir_offset": 0.0,
                    "output_nodata": -9999.0,
                    "add_to_project": False,
                }
            )
        except BridgeError as error:
            calibration_error = error.code
        report["steps"]["raster_calibration_guard"] = calibration_error == "CALIBRATION_CONFLICT"
        print("SMOKE_STEP raster_calibration_guard", flush=True)

        raster_analysis = operations.op_analyze_raster_colors(
            {
                "layer_id": red_layer.id(),
                "band_numbers": [1],
                "histogram_bins": 4,
                "sample_size": 100,
            }
        )
        report["steps"]["raster_analysis"] = (
            raster_analysis["bands"][0]["valid_pixel_count"] == 3
            and raster_analysis["value_domain"] == "raw_band_values"
        )
        print("SMOKE_STEP raster_analysis", flush=True)

        raster_style = operations.op_apply_raster_style(
            {
                "layer_id": red_layer.id(),
                "mode": "pseudocolor",
                "band": 1,
                "classes": [
                    {"value": 0.0, "color": "#440154", "label": "low"},
                    {"value": 0.5, "color": "#21918c", "label": "middle"},
                    {"value": 1.0, "color": "#fde725", "label": "high"},
                ],
                "interpolation": "linear",
            }
        )
        report["steps"]["raster_style"] = raster_style["renderer_type"] == "singlebandpseudocolor"
        print("SMOKE_STEP raster_style", flush=True)

        prepared = operations.op_prepare_raster(
            {
                "layer_id": red_layer.id(),
                "reference_layer_id": nir_layer.id(),
                "output_path": str(runtime_dir / "prepared.tif"),
                "bbox": None,
                "resampling": "nearest",
                "output_nodata": -9999.0,
                "add_to_project": False,
            }
        )
        prepared_job = _wait_for_job(app, jobs, prepared["job_id"])
        prepared_dataset = gdal.Open(str(runtime_dir / "prepared.tif"))
        report["steps"]["prepare_raster"] = (
            prepared_job["status"] == "completed"
            and prepared_dataset is not None
            and prepared_dataset.RasterXSize == 2
            and np.allclose(
                prepared_dataset.GetGeoTransform(),
                [120.0, 0.01, 0.0, 24.0, 0.0, -0.01],
            )
        )
        prepared_dataset = None
        print("SMOKE_STEP prepare_raster", flush=True)

        reprojected = operations.op_reproject_raster(
            {
                "layer_id": red_layer.id(),
                "output_path": str(runtime_dir / "reprojected.tif"),
                "target_crs": "EPSG:3857",
                "target_resolution": 1000.0,
                "bbox": None,
                "resampling": "bilinear",
                "output_nodata": -9999.0,
                "add_to_project": False,
            }
        )
        reprojected_job = _wait_for_job(app, jobs, reprojected["job_id"])
        reprojected_layer = QgsRasterLayer(str(runtime_dir / "reprojected.tif"), "reprojected", "gdal")
        report["steps"]["reproject_raster"] = (
            reprojected_job["status"] == "completed"
            and reprojected_layer.isValid()
            and reprojected_layer.crs() == QgsCoordinateReferenceSystem("EPSG:3857")
        )
        print("SMOKE_STEP reproject_raster", flush=True)

        ndvi = operations.op_calculate_ndvi(
            {
                "red_layer_id": red_layer.id(),
                "red_band": 1,
                "nir_layer_id": nir_layer.id(),
                "nir_band": 1,
                "output_path": str(runtime_dir / "ndvi.tif"),
                "calibration_mode": "reflectance",
                "red_scale": None,
                "red_offset": None,
                "nir_scale": None,
                "nir_offset": None,
                "mask_layer_id": mask_layer.id(),
                "mask_band": 1,
                "mask_valid_values": [1.0],
                "output_nodata": -9999.0,
                "add_to_project": True,
            }
        )
        ndvi_job = _wait_for_job(app, jobs, ndvi["job_id"])
        ndvi_dataset = gdal.Open(str(runtime_dir / "ndvi.tif"))
        ndvi_values = ndvi_dataset.GetRasterBand(1).ReadAsArray()
        ndvi_dataset = None
        report["steps"]["calculate_ndvi"] = (
            ndvi_job["status"] == "completed"
            and ndvi_job["result"]["valid_pixel_count"] == 1
            and abs(float(ndvi_values[0, 0]) - 0.5) < 1e-6
            and float(ndvi_values[0, 1]) == -9999.0
        )
        print("SMOKE_STEP calculate_ndvi", flush=True)

        metadata_ndvi = operations.op_calculate_ndvi(
            {
                "red_layer_id": calibrated_layer.id(),
                "red_band": 1,
                "nir_layer_id": calibrated_layer.id(),
                "nir_band": 1,
                "output_path": str(runtime_dir / "metadata-ndvi.tif"),
                "calibration_mode": "metadata",
                "red_scale": None,
                "red_offset": None,
                "nir_scale": None,
                "nir_offset": None,
                "mask_layer_id": "",
                "mask_band": 1,
                "mask_valid_values": [],
                "output_nodata": -9999.0,
                "add_to_project": False,
            }
        )
        metadata_ndvi_job = _wait_for_job(app, jobs, metadata_ndvi["job_id"])
        report["steps"]["metadata_calibration"] = (
            metadata_ndvi_job["status"] == "completed"
            and metadata_ndvi_job["result"]["valid_pixel_count"] == 4
            and bool(metadata_ndvi_job["warnings"])
        )
        print("SMOKE_STEP metadata_calibration", flush=True)

        converted = operations.op_convert_raster_format(
            {
                "layer_id": nir_layer.id(),
                "output_path": str(runtime_dir / "converted.tif"),
                "output_format": "COG",
                "compression": "DEFLATE",
                "block_size": 512,
                "add_to_project": False,
            }
        )
        converted_job = _wait_for_job(app, jobs, converted["job_id"])
        converted_dataset = gdal.Open(str(runtime_dir / "converted.tif"))
        report["steps"]["convert_raster"] = (
            converted_job["status"] == "completed"
            and converted_dataset is not None
            and converted_dataset.GetDriver().ShortName == "GTiff"
            and (runtime_dir / "converted.tif.manifest.json").is_file()
        )
        converted_dataset = None
        print("SMOKE_STEP convert_raster", flush=True)

        ndvi_layer_id = ndvi_job["result"]["added_layers"][0]["layer_id"]
        zonal = operations.op_run_zonal_statistics(
            {
                "raster_layer_id": ndvi_layer_id,
                "zones_layer_id": zone_layer.id(),
                "output_path": str(runtime_dir / "zonal.gpkg"),
                "raster_band": 1,
                "column_prefix": "ndvi_",
                "statistics": ["count", "mean", "minimum", "maximum"],
                "add_to_project": False,
            }
        )
        zonal_job = _wait_for_job(app, jobs, zonal["job_id"])
        zonal_layer = QgsVectorLayer(str(runtime_dir / "zonal.gpkg"), "zonal", "ogr")
        report["steps"]["zonal_statistics"] = (
            zonal_job["status"] == "completed"
            and zonal_layer.isValid()
            and zonal_layer.featureCount() == 1
            and zonal_layer.fields().indexOf("ndvi_mean") >= 0
        )
        print("SMOKE_STEP zonal_statistics", flush=True)

        def cancellable_worker(task):
            """等待取消旗標，驗證請求與實際停止是兩個不同狀態。"""
            for index in range(1000):
                if task.isCanceled():
                    return {"cancelled_at": index}
                task.setProgress(index / 10)
                time.sleep(0.001)
            return {"cancelled_at": None}

        cancellable = jobs.start_callable(
            "Cancellation smoke test",
            cancellable_worker,
            "cancellation_smoke",
            False,
        )
        cancellation_deadline = time.monotonic() + 5
        while jobs.get_status(cancellable["job_id"])["status"] == "queued":
            if time.monotonic() >= cancellation_deadline:
                raise TimeoutError("Cancellable task did not start")
            app.processEvents()
            time.sleep(0.005)
        cancellation_requested = jobs.cancel(cancellable["job_id"])
        cancellation_completed = _wait_for_job(app, jobs, cancellable["job_id"])
        report["steps"]["job_cancellation"] = (
            cancellation_requested["status"] == "cancelling"
            and cancellation_completed["status"] == "cancelled"
        )
        print("SMOKE_STEP job_cancellation", flush=True)

        processing = operations.op_run_processing_algorithm(
            {
                "algorithm_id": "native:buffer",
                "parameters": {
                    "INPUT": layer.id(),
                    "DISTANCE": 0.01,
                    "SEGMENTS": 5,
                    "END_CAP_STYLE": 0,
                    "JOIN_STYLE": 0,
                    "MITER_LIMIT": 2.0,
                    "DISSOLVE": False,
                    "OUTPUT": "TEMPORARY_OUTPUT",
                },
                "add_outputs_to_project": True,
            }
        )
        second_processing = operations.op_run_processing_algorithm(
            {
                "algorithm_id": "native:buffer",
                "parameters": {
                    "INPUT": layer.id(),
                    "DISTANCE": 0.02,
                    "SEGMENTS": 5,
                    "END_CAP_STYLE": 0,
                    "JOIN_STYLE": 0,
                    "MITER_LIMIT": 2.0,
                    "DISSOLVE": False,
                    "OUTPUT": "TEMPORARY_OUTPUT",
                },
                "add_outputs_to_project": True,
            }
        )
        completed_job = _wait_for_job(app, jobs, processing["job_id"])
        completed_second_job = _wait_for_job(app, jobs, second_processing["job_id"])
        report["steps"]["processing_buffer"] = (
            completed_job["status"] == "completed" and completed_second_job["status"] == "completed"
        )
        report["steps"]["processing_queue"] = second_processing["status"] == "queued"
        print("SMOKE_STEP processing_buffer", flush=True)
        print("SMOKE_STEP processing_queue", flush=True)
        report["processing_job"] = completed_job
        report["second_processing_job"] = completed_second_job
        report["confirmation_count"] = len(confirmation.requests)
        report["confirmed_operations"] = confirmation.requests
        report["success"] = all(report["steps"].values())
        return report
    finally:
        bridge.stop()
        QgsProject.instance().clear()
        QgsApplication.processingRegistry().removeProvider(native_provider)
        jobs._jobs.clear()  # 測試程序退出前釋放已完成 task 的 SIP 參照。
        layer = red_layer = nir_layer = mask_layer = shifted_layer = calibrated_layer = zone_layer = None
        reprojected_layer = zonal_layer = None
        jobs.deleteLater()
        app.processEvents()
        app.exitQgis()


def main() -> int:
    """寫入 JSON 報告並以 exit code 表示 smoke-test 結果。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = run_smoke()
    safe_version = str(report["qgis_version"]).split("-")[0].replace(".", "_")
    report_path = OUTPUT_DIR / f"qgis_{safe_version}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "success": report["success"]}, ensure_ascii=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
