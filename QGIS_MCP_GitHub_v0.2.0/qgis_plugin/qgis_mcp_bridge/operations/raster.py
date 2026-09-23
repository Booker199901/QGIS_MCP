"""通用本機 Raster 檢查、前處理、NDVI、統計、樣式與成果輸出。"""

from __future__ import annotations

import json
import math
import os
import uuid
from contextlib import suppress
from pathlib import Path

import numpy as np
from osgeo import gdal
from qgis.core import (
    QgsApplication,
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsMultiBandColorRenderer,
    QgsRasterShader,
    QgsSingleBandGrayRenderer,
    QgsSingleBandPseudoColorRenderer,
    QgsWkbTypes,
)
from qgis.PyQt.QtGui import QColor

from ..constants import PLUGIN_VERSION
from ..errors import BridgeError
from ..utils import (
    absolute_output_path,
    crs_dict,
    rectangle_dict,
    require_bbox,
    require_bool,
    require_float,
    require_int,
    require_string,
)

RASTER_SUFFIXES = {".tif", ".tiff"}
RESAMPLING_ALGORITHMS = {
    "nearest": gdal.GRA_NearestNeighbour,
    "bilinear": gdal.GRA_Bilinear,
    "cubic": gdal.GRA_Cubic,
    "lanczos": gdal.GRA_Lanczos,
    "average": gdal.GRA_Average,
    "mode": gdal.GRA_Mode,
}
ZONAL_STATISTICS = {
    "count": 0,
    "sum": 1,
    "mean": 2,
    "median": 3,
    "stdev": 4,
    "minimum": 5,
    "maximum": 6,
    "range": 7,
    "minority": 8,
    "majority": 9,
    "variety": 10,
    "variance": 11,
}
DEFAULT_NDVI_NODATA = -9999.0
NDVI_BLOCK_ROWS = 512
MANIFEST_SCHEMA_VERSION = 1


class RasterOperations:
    """提供不猜測波段、校正或 CRS 的可重現 Raster 工作。"""

    def op_get_raster_info(self, params):
        """取得 Raster 網格、各波段 NoData、scale、offset 與 metadata。"""
        snapshot = self._raster_snapshot(require_string(params, "layer_id"))
        return {
            "layer_id": snapshot["layer_id"],
            "name": snapshot["name"],
            "source": snapshot["source"],
            "driver": snapshot["driver"],
            "width": snapshot["width"],
            "height": snapshot["height"],
            "band_count": len(snapshot["bands"]),
            "bands": snapshot["bands"],
            "crs": snapshot["crs"],
            "extent": snapshot["extent"],
            "geotransform": snapshot["geotransform"],
            "pixel_size": {
                "x": abs(snapshot["geotransform"][1]),
                "y": abs(snapshot["geotransform"][5]),
            },
            "metadata": snapshot["metadata"],
            "calibration_warning": (
                "scale/offset 為空表示來源未宣告校正資訊；不可據此假設像元已是反射率。"
            ),
        }

    def op_prepare_raster(self, params):
        """將本機 Raster 裁切並精確對齊至指定參考 Raster 的像元網格。"""
        source = self._raster_snapshot(require_string(params, "layer_id"))
        reference = self._raster_snapshot(require_string(params, "reference_layer_id"))
        self._require_crs(source, "來源 Raster")
        self._require_crs(reference, "參考 Raster")
        output_path = absolute_output_path(require_string(params, "output_path"), RASTER_SUFFIXES)
        resampling = self._resampling(params)
        output_nodata = self._output_nodata(params, source)
        add_to_project = require_bool(params, "add_to_project", True)
        bbox_rect = require_bbox(params.get("bbox"))
        bounds, width, height = self._reference_grid(reference, bbox_rect)
        self.confirm_overwrite(output_path, "覆寫 Raster 前處理成果")
        manifest = self._manifest_base(
            "prepare_raster",
            [source],
            {
                "reference_layer_id": reference["layer_id"],
                "bounds": bounds,
                "width": width,
                "height": height,
                "resampling": resampling,
                "output_nodata": output_nodata,
            },
        )

        def worker(task):
            return RasterOperations._warp_worker(
                task,
                source,
                output_path,
                reference["projection_wkt"],
                bounds,
                width,
                height,
                None,
                resampling,
                output_nodata,
                manifest,
            )

        job = self.jobs.start_callable(
            "Prepare aligned raster",
            worker,
            "prepare_raster",
            add_to_project,
            {"output_path": str(output_path)},
        )
        return {"status": "queued", **job}

    def op_reproject_raster(self, params):
        """以明確目標 CRS、解析度、重採樣與 NoData 建立新 Raster。"""
        source = self._raster_snapshot(require_string(params, "layer_id"))
        self._require_crs(source, "來源 Raster")
        output_path = absolute_output_path(require_string(params, "output_path"), RASTER_SUFFIXES)
        target_crs_text = require_string(params, "target_crs")
        if not QgsCoordinateReferenceSystem(target_crs_text).isValid():
            raise BridgeError("INVALID_PARAMETERS", f"無效 target_crs：{target_crs_text}")
        target_resolution = require_float(params, "target_resolution", minimum=1e-12)
        resampling = self._resampling(params)
        output_nodata = self._output_nodata(params, source)
        add_to_project = require_bool(params, "add_to_project", True)
        bbox_rect = require_bbox(params.get("bbox"))
        bounds = None
        if bbox_rect is not None:
            bounds = [
                bbox_rect.xMinimum(),
                bbox_rect.yMinimum(),
                bbox_rect.xMaximum(),
                bbox_rect.yMaximum(),
            ]
        self.confirm_overwrite(output_path, "覆寫 Raster 重投影成果")
        manifest = self._manifest_base(
            "reproject_raster",
            [source],
            {
                "target_crs": target_crs_text,
                "target_resolution": target_resolution,
                "bounds": bounds,
                "resampling": resampling,
                "output_nodata": output_nodata,
            },
        )

        def worker(task):
            return RasterOperations._warp_worker(
                task,
                source,
                output_path,
                target_crs_text,
                bounds,
                None,
                None,
                target_resolution,
                resampling,
                output_nodata,
                manifest,
            )

        job = self.jobs.start_callable(
            "Reproject raster",
            worker,
            "reproject_raster",
            add_to_project,
            {"output_path": str(output_path)},
        )
        return {"status": "queued", **job}

    def op_calculate_ndvi(self, params):
        """依明確 Red/NIR 波段、校正模式與品質遮罩計算 Float32 NDVI。"""
        red = self._raster_snapshot(require_string(params, "red_layer_id"))
        nir = self._raster_snapshot(require_string(params, "nir_layer_id"))
        self._require_crs(red, "Red Raster")
        self._require_crs(nir, "NIR Raster")
        red_band = require_int(params, "red_band", minimum=1, maximum=len(red["bands"]))
        nir_band = require_int(params, "nir_band", minimum=1, maximum=len(nir["bands"]))
        self._require_matching_grids(red, nir, "Red 與 NIR")
        calibration_mode = params.get("calibration_mode", "reflectance")
        if calibration_mode not in {"reflectance", "metadata", "explicit"}:
            raise BridgeError(
                "INVALID_PARAMETERS",
                "calibration_mode 必須是 reflectance、metadata 或 explicit。",
            )
        red_calibration = self._calibration(params, red, red_band, "red", calibration_mode)
        nir_calibration = self._calibration(params, nir, nir_band, "nir", calibration_mode)
        mask = None
        mask_band = None
        mask_values = params.get("mask_valid_values", [])
        mask_layer_id = params.get("mask_layer_id")
        if mask_layer_id:
            if not isinstance(mask_layer_id, str):
                raise BridgeError("INVALID_PARAMETERS", "mask_layer_id 必須是字串。")
            mask = self._raster_snapshot(mask_layer_id)
            self._require_crs(mask, "品質遮罩 Raster")
            self._require_matching_grids(red, mask, "Red 與品質遮罩")
            mask_band = require_int(params, "mask_band", 1, minimum=1, maximum=len(mask["bands"]))
            if not isinstance(mask_values, list) or not mask_values:
                raise BridgeError("INVALID_PARAMETERS", "使用品質遮罩時必須提供 mask_valid_values。")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in mask_values):
                raise BridgeError("INVALID_PARAMETERS", "mask_valid_values 必須是數值列表。")
            mask_values = [float(value) for value in mask_values]
            if any(not math.isfinite(value) for value in mask_values):
                raise BridgeError("INVALID_PARAMETERS", "mask_valid_values 必須是有限數值。")
        elif mask_values:
            raise BridgeError("INVALID_PARAMETERS", "提供 mask_valid_values 時也必須提供 mask_layer_id。")
        output_path = absolute_output_path(require_string(params, "output_path"), RASTER_SUFFIXES)
        output_nodata = require_float(params, "output_nodata", DEFAULT_NDVI_NODATA)
        if -1.0 <= output_nodata <= 1.0:
            raise BridgeError("INVALID_PARAMETERS", "NDVI output_nodata 必須位於 -1 至 1 以外。")
        add_to_project = require_bool(params, "add_to_project", True)
        self.confirm_overwrite(output_path, "覆寫 NDVI 成果")
        manifest = self._manifest_base(
            "calculate_ndvi",
            [red, nir] + ([mask] if mask else []),
            {
                "red_band": red_band,
                "nir_band": nir_band,
                "calibration_mode": calibration_mode,
                "red_calibration": red_calibration,
                "nir_calibration": nir_calibration,
                "mask_band": mask_band,
                "mask_valid_values": mask_values,
                "output_nodata": output_nodata,
            },
        )

        def worker(task):
            return RasterOperations._ndvi_worker(
                task,
                red,
                red_band,
                red_calibration,
                nir,
                nir_band,
                nir_calibration,
                mask,
                mask_band,
                mask_values,
                output_path,
                output_nodata,
                manifest,
            )

        job = self.jobs.start_callable(
            "Calculate NDVI",
            worker,
            "calculate_ndvi",
            add_to_project,
            {"output_path": str(output_path)},
        )
        return {"status": "queued", **job}

    def op_analyze_raster_colors(self, params):
        """抽樣 Raster 原始像元，排除 NoData 後回傳統計與直方圖。"""
        snapshot = self._raster_snapshot(require_string(params, "layer_id"))
        requested_bands = params.get("band_numbers") or list(range(1, len(snapshot["bands"]) + 1))
        if not isinstance(requested_bands, list) or not requested_bands:
            raise BridgeError("INVALID_PARAMETERS", "band_numbers 必須是非空列表。")
        if len(requested_bands) > 64:
            raise BridgeError("INVALID_PARAMETERS", "單次最多分析 64 個 band。")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in requested_bands):
            raise BridgeError("INVALID_PARAMETERS", "band_numbers 必須是整數列表。")
        if len(set(requested_bands)) != len(requested_bands):
            raise BridgeError("INVALID_PARAMETERS", "band_numbers 不可重複。")
        for band_number in requested_bands:
            if not 1 <= band_number <= len(snapshot["bands"]):
                raise BridgeError("INVALID_PARAMETERS", f"Raster 不存在 band {band_number}。")
        histogram_bins = require_int(params, "histogram_bins", 32, minimum=2, maximum=256)
        sample_size = require_int(params, "sample_size", 250_000, minimum=100, maximum=1_000_000)
        dataset = self._open_dataset(snapshot["source"])
        pixels_per_band = max(1, sample_size // len(requested_bands))
        scale = min(
            1.0,
            math.sqrt(pixels_per_band / max(1, snapshot["width"] * snapshot["height"])),
        )
        sample_width = max(1, int(snapshot["width"] * scale))
        sample_height = max(1, int(snapshot["height"] * scale))
        bands = []
        try:
            for band_number in requested_bands:
                band = dataset.GetRasterBand(band_number)
                values = band.ReadAsArray(buf_xsize=sample_width, buf_ysize=sample_height)
                mask_values = band.GetMaskBand().ReadAsArray(
                    buf_xsize=sample_width,
                    buf_ysize=sample_height,
                )
                valid = np.isfinite(values) & (mask_values != 0)
                nodata = band.GetNoDataValue()
                if nodata is not None:
                    valid &= values != nodata
                valid_values = values[valid].astype(np.float64, copy=False)
                bands.append(
                    self._sample_statistics(
                        band_number,
                        valid_values,
                        values.size,
                        histogram_bins,
                    )
                )
        finally:
            dataset = None
        renderer = self.layer(snapshot["layer_id"], raster=True).renderer()
        return {
            "layer_id": snapshot["layer_id"],
            "value_domain": "raw_band_values",
            "renderer_type": renderer.type() if renderer else None,
            "sampling": {
                "method": "full_extent_uniform_resample",
                "requested_max_pixels": sample_size,
                "sample_width": sample_width,
                "sample_height": sample_height,
                "is_full_resolution": (
                    sample_width == snapshot["width"] and sample_height == snapshot["height"]
                ),
            },
            "bands": bands,
            "display_note": "統計來自原始 band 值，不代表 QGIS renderer 套用色帶後的畫面 RGB。",
        }

    def op_apply_raster_style(self, params):
        """套用 RGB、灰階或具有明確 breaks 的單波段色帶。"""
        layer = self.layer(require_string(params, "layer_id"), raster=True)
        provider = layer.dataProvider()
        mode = params.get("mode")
        if mode == "rgb":
            red_band = require_int(params, "red_band", minimum=1, maximum=layer.bandCount())
            green_band = require_int(params, "green_band", minimum=1, maximum=layer.bandCount())
            blue_band = require_int(params, "blue_band", minimum=1, maximum=layer.bandCount())
            renderer = QgsMultiBandColorRenderer(provider, red_band, green_band, blue_band)
            details = {"red_band": red_band, "green_band": green_band, "blue_band": blue_band}
        elif mode == "grayscale":
            band = require_int(params, "band", 1, minimum=1, maximum=layer.bandCount())
            renderer = QgsSingleBandGrayRenderer(provider, band)
            details = {"band": band}
        elif mode == "pseudocolor":
            band = require_int(params, "band", 1, minimum=1, maximum=layer.bandCount())
            classes = self._color_classes(params.get("classes"))
            interpolation = params.get("interpolation", "linear")
            interpolation_types = getattr(QgsColorRampShader, "Type", QgsColorRampShader)
            interpolation_map = {
                "linear": interpolation_types.Interpolated,
                "discrete": interpolation_types.Discrete,
                "exact": interpolation_types.Exact,
            }
            if interpolation not in interpolation_map:
                raise BridgeError("INVALID_PARAMETERS", "interpolation 必須是 linear、discrete 或 exact。")
            ramp = QgsColorRampShader(classes[0]["value"], classes[-1]["value"])
            ramp.setColorRampType(interpolation_map[interpolation])
            items = [
                QgsColorRampShader.ColorRampItem(item["value"], QColor(item["color"]), item["label"])
                for item in classes
            ]
            ramp.setColorRampItemList(items)
            shader = QgsRasterShader()
            shader.setRasterShaderFunction(ramp)
            renderer = QgsSingleBandPseudoColorRenderer(provider, band, shader)
            details = {"band": band, "interpolation": interpolation, "classes": classes}
        else:
            raise BridgeError("INVALID_PARAMETERS", "mode 必須是 rgb、grayscale 或 pseudocolor。")
        layer.setRenderer(renderer)
        layer.triggerRepaint()
        self.iface.layerTreeView().refreshLayerSymbology(layer.id())
        self.iface.mapCanvas().refresh()
        return {"layer_id": layer.id(), "mode": mode, "renderer_type": renderer.type(), **details}

    def op_run_zonal_statistics(self, params):
        """以 QGIS 原生演算法計算完整像元的分區統計並原子交付 GeoPackage。"""
        raster = self._raster_snapshot(require_string(params, "raster_layer_id"))
        self._require_crs(raster, "統計 Raster")
        raster_band = require_int(params, "raster_band", 1, minimum=1, maximum=len(raster["bands"]))
        zones = self.layer(require_string(params, "zones_layer_id"), vector=True)
        if QgsWkbTypes.geometryType(zones.wkbType()) != QgsWkbTypes.PolygonGeometry:
            raise BridgeError("INVALID_PARAMETERS", "zones_layer_id 必須是多邊形圖層。")
        if not zones.crs().isValid():
            raise BridgeError("CRS_REQUIRED", "分區圖層缺少有效 CRS。")
        output_path = absolute_output_path(require_string(params, "output_path"), {".gpkg"})
        prefix = require_string(params, "column_prefix", allow_empty=True)
        statistics = params.get("statistics", ["count", "mean", "minimum", "maximum"])
        if not isinstance(statistics, list) or not statistics:
            raise BridgeError("INVALID_PARAMETERS", "statistics 必須是非空列表。")
        unknown = sorted(set(statistics) - set(ZONAL_STATISTICS))
        if unknown:
            raise BridgeError("INVALID_PARAMETERS", "包含不支援的分區統計。", {"unknown": unknown})
        if len(set(statistics)) != len(statistics):
            raise BridgeError("INVALID_PARAMETERS", "statistics 不可重複。")
        add_to_project = require_bool(params, "add_to_project", True)
        algorithm = QgsApplication.processingRegistry().algorithmById("native:zonalstatisticsfb")
        if algorithm is None:
            raise BridgeError("PROCESSING_ALGORITHM_NOT_FOUND", "找不到 native:zonalstatisticsfb。")
        self.confirm_overwrite(output_path, "覆寫分區統計成果")
        temporary_path = self._temporary_path(output_path, "zonal")
        manifest = self._manifest_base(
            "run_zonal_statistics",
            [raster],
            {
                "zones_layer_id": zones.id(),
                "raster_band": raster_band,
                "column_prefix": prefix,
                "statistics": statistics,
            },
        )
        processing_params = {
            "INPUT": zones.id(),
            "INPUT_RASTER": raster["layer_id"],
            "RASTER_BAND": raster_band,
            "COLUMN_PREFIX": prefix,
            "STATISTICS": [ZONAL_STATISTICS[name] for name in statistics],
            "OUTPUT": str(temporary_path),
        }

        def finalize(results):
            produced_path = Path(str(results.get("OUTPUT", temporary_path)))
            if not produced_path.is_file():
                raise RuntimeError("Zonal statistics did not create its declared output")
            os.replace(produced_path, output_path)
            manifest_path = self._write_manifest(output_path, manifest)
            return {**results, "OUTPUT": str(output_path), "MANIFEST": str(manifest_path)}

        job = self.jobs.start_processing(
            algorithm,
            processing_params,
            add_to_project,
            result_transform=finalize,
            result_metadata={"output_path": str(output_path)},
        )
        return {"status": "queued", **job}

    def op_convert_raster_format(self, params):
        """將本機 Raster 轉為 GeoTIFF 或 COG，並輸出可重現 manifest。"""
        source = self._raster_snapshot(require_string(params, "layer_id"))
        output_path = absolute_output_path(require_string(params, "output_path"), RASTER_SUFFIXES)
        output_format = params.get("output_format", "COG")
        if output_format not in {"COG", "GTiff"}:
            raise BridgeError("INVALID_PARAMETERS", "output_format 必須是 COG 或 GTiff。")
        compression = params.get("compression", "DEFLATE")
        if compression not in {"DEFLATE", "LZW", "ZSTD", "NONE"}:
            raise BridgeError("INVALID_PARAMETERS", "compression 必須是 DEFLATE、LZW、ZSTD 或 NONE。")
        block_size = require_int(params, "block_size", 512, minimum=128, maximum=4096)
        add_to_project = require_bool(params, "add_to_project", True)
        self.confirm_overwrite(output_path, "覆寫 Raster 格式轉換成果")
        manifest = self._manifest_base(
            "convert_raster_format",
            [source],
            {"output_format": output_format, "compression": compression, "block_size": block_size},
        )

        def worker(task):
            return RasterOperations._translate_worker(
                task,
                source,
                output_path,
                output_format,
                compression,
                block_size,
                manifest,
            )

        job = self.jobs.start_callable(
            "Convert raster format",
            worker,
            "convert_raster_format",
            add_to_project,
            {"output_path": str(output_path), "output_format": output_format},
        )
        return {"status": "queued", **job}

    def _raster_snapshot(self, layer_id):
        """在 QGIS 主執行緒驗證圖層並只留下背景工作可安全使用的純資料。"""
        layer = self.layer(layer_id, raster=True)
        raw_source = layer.source().split("|", 1)[0]
        try:
            source_path = Path(raw_source).expanduser().resolve(strict=True)
        except OSError as error:
            raise BridgeError(
                "FILE_ACCESS_DENIED",
                "Raster 本機來源不存在或無法存取。",
            ) from error
        if not source_path.is_file():
            raise BridgeError("UNSUPPORTED_FORMAT", "此批 Raster 工具只支援本機檔案來源。")
        dataset = self._open_dataset(str(source_path))
        try:
            geotransform = dataset.GetGeoTransform(can_return_null=True)
            if geotransform is None:
                raise BridgeError("CRS_REQUIRED", "Raster 沒有可用的地理轉換資訊。")
            if not math.isclose(geotransform[2], 0.0, abs_tol=1e-12) or not math.isclose(
                geotransform[4], 0.0, abs_tol=1e-12
            ):
                raise BridgeError("UNSUPPORTED_FORMAT", "目前不支援旋轉或傾斜的像元網格。")
            bands = []
            for band_number in range(1, dataset.RasterCount + 1):
                band = dataset.GetRasterBand(band_number)
                scale = band.GetScale()
                offset = band.GetOffset()
                bands.append(
                    {
                        "band": band_number,
                        "name": band.GetDescription() or f"Band {band_number}",
                        "data_type": gdal.GetDataTypeName(band.DataType),
                        "nodata": band.GetNoDataValue(),
                        "scale": scale,
                        "offset": offset,
                        "has_scale_offset_metadata": scale is not None or offset is not None,
                        "color_interpretation": gdal.GetColorInterpretationName(
                            band.GetColorInterpretation()
                        ),
                        "metadata": band.GetMetadata(),
                    }
                )
            return {
                "layer_id": layer.id(),
                "name": layer.name(),
                "source": str(source_path),
                "driver": dataset.GetDriver().ShortName,
                "width": dataset.RasterXSize,
                "height": dataset.RasterYSize,
                "bands": bands,
                "geotransform": list(geotransform),
                "projection_wkt": dataset.GetProjectionRef(),
                "crs": crs_dict(layer.crs()),
                "extent": rectangle_dict(layer.extent()),
                "metadata": dataset.GetMetadata(),
            }
        finally:
            dataset = None

    @staticmethod
    def _open_dataset(source):
        """以唯讀方式開啟本機 Raster，失敗時不回傳 GDAL 的敏感完整錯誤。"""
        dataset = gdal.OpenEx(source, gdal.OF_RASTER | gdal.OF_READONLY)
        if dataset is None:
            raise BridgeError("UNSUPPORTED_FORMAT", "GDAL 無法開啟指定 Raster。")
        return dataset

    @staticmethod
    def _require_crs(snapshot, label):
        """需要空間操作時明確拒絕缺少 CRS 的 Raster。"""
        if not snapshot["crs"]["is_valid"] or not snapshot["projection_wkt"]:
            raise BridgeError("CRS_REQUIRED", f"{label} 缺少有效 CRS。")

    @staticmethod
    def _resampling(params):
        """驗證重採樣方法，預設適用連續影像的 bilinear。"""
        value = params.get("resampling", "bilinear")
        if value not in RESAMPLING_ALGORITHMS:
            raise BridgeError("INVALID_PARAMETERS", "不支援的 resampling。")
        return value

    @staticmethod
    def _output_nodata(params, snapshot):
        """要求明確 NoData，除非來源每個 band 都已有宣告。"""
        value = params.get("output_nodata")
        if value is not None:
            return require_float(params, "output_nodata")
        source_values = {band["nodata"] for band in snapshot["bands"]}
        if len(source_values) == 1 and None not in source_values:
            return source_values.pop()
        raise BridgeError(
            "INVALID_PARAMETERS",
            "來源未為所有 band 宣告相同 NoData；請明確提供 output_nodata。",
        )

    @staticmethod
    def _reference_grid(reference, bbox_rect):
        """將 bbox 向外吸附到參考 Raster 網格，回傳固定 bounds 與尺寸。"""
        transform = reference["geotransform"]
        x_origin, x_size = transform[0], transform[1]
        y_origin, y_size = transform[3], transform[5]
        if x_size <= 0 or y_size >= 0:
            raise BridgeError("UNSUPPORTED_FORMAT", "只支援 north-up Raster 網格。")
        if bbox_rect is None:
            col_start, row_start = 0, 0
            col_end, row_end = reference["width"], reference["height"]
        else:
            col_start = max(0, math.floor((bbox_rect.xMinimum() - x_origin) / x_size))
            col_end = min(reference["width"], math.ceil((bbox_rect.xMaximum() - x_origin) / x_size))
            row_start = max(0, math.floor((bbox_rect.yMaximum() - y_origin) / y_size))
            row_end = min(reference["height"], math.ceil((bbox_rect.yMinimum() - y_origin) / y_size))
            if col_start >= col_end or row_start >= row_end:
                raise BridgeError("INVALID_PARAMETERS", "bbox 與參考 Raster 沒有重疊。")
        xmin = x_origin + col_start * x_size
        xmax = x_origin + col_end * x_size
        ymax = y_origin + row_start * y_size
        ymin = y_origin + row_end * y_size
        return [xmin, ymin, xmax, ymax], col_end - col_start, row_end - row_start

    @staticmethod
    def _require_matching_grids(first, second, label):
        """嚴格檢查 CRS、尺寸、像元解析度與原點，阻止錯位像元運算。"""
        same_shape = first["width"] == second["width"] and first["height"] == second["height"]
        same_projection = first["projection_wkt"] == second["projection_wkt"]
        same_transform = all(
            math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
            for a, b in zip(first["geotransform"], second["geotransform"], strict=True)
        )
        if not (same_shape and same_projection and same_transform):
            raise BridgeError(
                "RASTER_ALIGNMENT_REQUIRED",
                f"{label} 的 CRS、尺寸、像元解析度或原點不一致；請先使用 prepare_raster。",
                {
                    "first_layer_id": first["layer_id"],
                    "second_layer_id": second["layer_id"],
                    "same_shape": same_shape,
                    "same_projection": same_projection,
                    "same_geotransform": same_transform,
                },
            )

    @staticmethod
    def _calibration(params, snapshot, band_number, prefix, mode):
        """解析單一 band 校正，並拒絕與來源 metadata 衝突的重複校正。"""
        band = snapshot["bands"][band_number - 1]
        metadata_scale = band["scale"]
        metadata_offset = band["offset"]
        has_metadata = band["has_scale_offset_metadata"]
        if mode == "reflectance":
            if has_metadata and (
                not math.isclose(metadata_scale if metadata_scale is not None else 1.0, 1.0)
                or not math.isclose(metadata_offset if metadata_offset is not None else 0.0, 0.0)
            ):
                raise BridgeError(
                    "CALIBRATION_CONFLICT",
                    f"{prefix} band 宣告非單位 scale/offset，與 reflectance 模式衝突。",
                )
            return {"scale": 1.0, "offset": 0.0, "source": "caller_declared_reflectance"}
        if mode == "metadata":
            if not has_metadata:
                raise BridgeError(
                    "CALIBRATION_REQUIRED",
                    f"{prefix} band 沒有 scale/offset metadata；請改用 explicit 或 reflectance。",
                )
            if metadata_scale == 0:
                raise BridgeError("CALIBRATION_REQUIRED", f"{prefix} band 的 metadata scale 不可為 0。")
            return {
                "scale": metadata_scale if metadata_scale is not None else 1.0,
                "offset": metadata_offset if metadata_offset is not None else 0.0,
                "source": "dataset_metadata",
            }
        scale = require_float(params, f"{prefix}_scale")
        offset = require_float(params, f"{prefix}_offset")
        if scale == 0:
            raise BridgeError("INVALID_PARAMETERS", f"{prefix}_scale 不可為 0。")
        if has_metadata:
            declared_scale = metadata_scale if metadata_scale is not None else 1.0
            declared_offset = metadata_offset if metadata_offset is not None else 0.0
            if not math.isclose(scale, declared_scale) or not math.isclose(offset, declared_offset):
                raise BridgeError(
                    "CALIBRATION_CONFLICT",
                    f"{prefix} 明確校正值與 Raster metadata 衝突。",
                )
        return {"scale": scale, "offset": offset, "source": "explicit"}

    @staticmethod
    def _gdal_progress(task, start=0.0, span=100.0):
        """建立可取消並映射至工作進度的 GDAL callback。"""
        def callback(complete, _message, _data):
            task.setProgress(start + max(0.0, min(1.0, complete)) * span)
            return 0 if task.isCanceled() else 1

        return callback

    @staticmethod
    def _warp_worker(
        task,
        source,
        output_path,
        target_crs,
        bounds,
        width,
        height,
        target_resolution,
        resampling,
        output_nodata,
        manifest,
    ):
        """在背景以 GDAL Warp 產生同資料夾暫存檔，驗證後原子交付。"""
        temporary_path = RasterOperations._temporary_path(output_path, "warp")
        try:
            options = {
                "format": "COG",
                "dstSRS": target_crs,
                "resampleAlg": RESAMPLING_ALGORITHMS[resampling],
                "dstNodata": output_nodata,
                "multithread": True,
                "creationOptions": ["COMPRESS=DEFLATE", "BLOCKSIZE=512"],
                "callback": RasterOperations._gdal_progress(task),
            }
            if bounds is not None:
                options["outputBounds"] = bounds
            if width is not None and height is not None:
                options["width"] = width
                options["height"] = height
            if target_resolution is not None:
                options["xRes"] = target_resolution
                options["yRes"] = target_resolution
                options["targetAlignedPixels"] = True
            result = gdal.Warp(str(temporary_path), source["source"], options=gdal.WarpOptions(**options))
            if result is None:
                raise RuntimeError("GDAL Warp failed")
            result.FlushCache()
            result = None
            if task.isCanceled():
                raise RuntimeError("cancelled")
            RasterOperations._validate_raster_output(temporary_path)
            os.replace(temporary_path, output_path)
            manifest_path = RasterOperations._write_manifest(output_path, manifest)
            return {
                "outputs": {"OUTPUT": str(output_path)},
                "manifest_path": str(manifest_path),
                "layer_paths": [str(output_path)],
            }
        finally:
            RasterOperations._remove_if_exists(temporary_path)

    @staticmethod
    def _ndvi_worker(
        task,
        red,
        red_band_number,
        red_calibration,
        nir,
        nir_band_number,
        nir_calibration,
        mask,
        mask_band_number,
        mask_valid_values,
        output_path,
        output_nodata,
        manifest,
    ):
        """以固定列區塊計算 NDVI，避免將大型影像完整載入記憶體。"""
        work_path = RasterOperations._temporary_path(output_path, "ndvi-work")
        delivery_path = RasterOperations._temporary_path(output_path, "ndvi-cog")
        red_dataset = RasterOperations._open_dataset(red["source"])
        nir_dataset = RasterOperations._open_dataset(nir["source"])
        mask_dataset = RasterOperations._open_dataset(mask["source"]) if mask else None
        output_dataset = None
        try:
            driver = gdal.GetDriverByName("GTiff")
            output_dataset = driver.Create(
                str(work_path),
                red["width"],
                red["height"],
                1,
                gdal.GDT_Float32,
                options=["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
            )
            if output_dataset is None:
                raise RuntimeError("Unable to create temporary NDVI GeoTIFF")
            output_dataset.SetGeoTransform(red["geotransform"])
            output_dataset.SetProjection(red["projection_wkt"])
            output_band = output_dataset.GetRasterBand(1)
            output_band.SetNoDataValue(output_nodata)
            output_band.SetDescription("NDVI")
            red_band = red_dataset.GetRasterBand(red_band_number)
            nir_band = nir_dataset.GetRasterBand(nir_band_number)
            mask_band = mask_dataset.GetRasterBand(mask_band_number) if mask_dataset else None
            valid_count = 0
            total_count = red["width"] * red["height"]
            outside_range_count = 0
            finite_min = math.inf
            finite_max = -math.inf
            for row in range(0, red["height"], NDVI_BLOCK_ROWS):
                if task.isCanceled():
                    raise RuntimeError("cancelled")
                row_count = min(NDVI_BLOCK_ROWS, red["height"] - row)
                red_raw = red_band.ReadAsArray(0, row, red["width"], row_count)
                nir_raw = nir_band.ReadAsArray(0, row, nir["width"], row_count)
                valid = np.isfinite(red_raw) & np.isfinite(nir_raw)
                red_nodata = red_band.GetNoDataValue()
                nir_nodata = nir_band.GetNoDataValue()
                if red_nodata is not None:
                    valid &= red_raw != red_nodata
                if nir_nodata is not None:
                    valid &= nir_raw != nir_nodata
                valid &= red_band.GetMaskBand().ReadAsArray(0, row, red["width"], row_count) != 0
                valid &= nir_band.GetMaskBand().ReadAsArray(0, row, nir["width"], row_count) != 0
                if mask_band is not None:
                    quality = mask_band.ReadAsArray(0, row, mask["width"], row_count)
                    valid &= np.isin(quality, mask_valid_values)
                    valid &= mask_band.GetMaskBand().ReadAsArray(0, row, mask["width"], row_count) != 0
                red_values = red_raw.astype(np.float64) * red_calibration["scale"] + red_calibration["offset"]
                nir_values = nir_raw.astype(np.float64) * nir_calibration["scale"] + nir_calibration["offset"]
                denominator = nir_values + red_values
                valid &= np.isfinite(red_values) & np.isfinite(nir_values) & (denominator != 0)
                result = np.full(red_raw.shape, output_nodata, dtype=np.float32)
                result[valid] = (
                    (nir_values[valid] - red_values[valid]) / denominator[valid]
                ).astype(np.float32)
                output_band.WriteArray(result, 0, row)
                block_values = result[valid]
                if block_values.size:
                    valid_count += int(block_values.size)
                    outside_range_count += int(np.count_nonzero((block_values < -1.0) | (block_values > 1.0)))
                    finite_min = min(finite_min, float(block_values.min()))
                    finite_max = max(finite_max, float(block_values.max()))
                task.setProgress(85.0 * (row + row_count) / red["height"])
            output_band.FlushCache()
            output_dataset.FlushCache()
            output_dataset = None
            translate = gdal.Translate(
                str(delivery_path),
                str(work_path),
                options=gdal.TranslateOptions(
                    format="COG",
                    creationOptions=["COMPRESS=DEFLATE", "BLOCKSIZE=512"],
                    callback=RasterOperations._gdal_progress(task, 85.0, 15.0),
                ),
            )
            if translate is None:
                raise RuntimeError("Unable to create NDVI COG")
            translate.FlushCache()
            translate = None
            if task.isCanceled():
                raise RuntimeError("cancelled")
            RasterOperations._validate_raster_output(delivery_path)
            os.replace(delivery_path, output_path)
            manifest["result"] = {
                "total_pixel_count": total_count,
                "valid_pixel_count": valid_count,
                "valid_pixel_percent": 100.0 * valid_count / total_count if total_count else 0.0,
                "outside_expected_range_count": outside_range_count,
                "minimum": finite_min if valid_count else None,
                "maximum": finite_max if valid_count else None,
            }
            manifest_path = RasterOperations._write_manifest(output_path, manifest)
            warnings = []
            if mask is None:
                warnings.append("未提供品質遮罩；成果未排除雲、陰影或其他來源品質旗標。")
            if outside_range_count:
                warnings.append(
                    f"有 {outside_range_count} 個有限 NDVI 像元超出 -1 至 1；數值已保留，請檢查校正。"
                )
            return {
                "outputs": {"OUTPUT": str(output_path)},
                "manifest_path": str(manifest_path),
                "valid_pixel_count": valid_count,
                "total_pixel_count": total_count,
                "valid_pixel_percent": 100.0 * valid_count / total_count if total_count else 0.0,
                "outside_expected_range_count": outside_range_count,
                "minimum": finite_min if valid_count else None,
                "maximum": finite_max if valid_count else None,
                "layer_paths": [str(output_path)],
                "warnings": warnings,
            }
        finally:
            output_dataset = None
            red_dataset = None
            nir_dataset = None
            mask_dataset = None
            RasterOperations._remove_if_exists(work_path)
            RasterOperations._remove_if_exists(delivery_path)

    @staticmethod
    def _translate_worker(task, source, output_path, output_format, compression, block_size, manifest):
        """以 GDAL Translate 建立完整暫存成果，驗證後才替換目標。"""
        temporary_path = RasterOperations._temporary_path(output_path, "translate")
        try:
            options = []
            if compression != "NONE":
                options.append(f"COMPRESS={compression}")
            if output_format == "COG":
                options.append(f"BLOCKSIZE={block_size}")
            else:
                options.extend(["TILED=YES", f"BLOCKXSIZE={block_size}", f"BLOCKYSIZE={block_size}"])
            result = gdal.Translate(
                str(temporary_path),
                source["source"],
                options=gdal.TranslateOptions(
                    format=output_format,
                    creationOptions=options,
                    callback=RasterOperations._gdal_progress(task),
                ),
            )
            if result is None:
                raise RuntimeError("GDAL Translate failed")
            result.FlushCache()
            result = None
            if task.isCanceled():
                raise RuntimeError("cancelled")
            RasterOperations._validate_raster_output(temporary_path)
            os.replace(temporary_path, output_path)
            manifest_path = RasterOperations._write_manifest(output_path, manifest)
            return {
                "outputs": {"OUTPUT": str(output_path)},
                "manifest_path": str(manifest_path),
                "layer_paths": [str(output_path)],
            }
        finally:
            RasterOperations._remove_if_exists(temporary_path)

    @staticmethod
    def _sample_statistics(band_number, values, sampled_count, histogram_bins):
        """計算有限抽樣統計；空 band 以 null 統計清楚表示。"""
        valid_count = int(values.size)
        common = {
            "band": band_number,
            "sampled_pixel_count": int(sampled_count),
            "valid_pixel_count": valid_count,
            "valid_pixel_percent": 100.0 * valid_count / sampled_count if sampled_count else 0.0,
        }
        if valid_count == 0:
            return {
                **common,
                "minimum": None,
                "maximum": None,
                "mean": None,
                "standard_deviation": None,
                "percentiles": {},
                "histogram": {"bin_edges": [], "counts": []},
            }
        minimum = float(values.min())
        maximum = float(values.max())
        histogram_range = (minimum - 0.5, maximum + 0.5) if minimum == maximum else (minimum, maximum)
        counts, edges = np.histogram(values, bins=histogram_bins, range=histogram_range)
        percentiles = np.percentile(values, [2, 25, 50, 75, 98])
        return {
            **common,
            "minimum": minimum,
            "maximum": maximum,
            "mean": float(values.mean()),
            "standard_deviation": float(values.std()),
            "percentiles": {
                "p02": float(percentiles[0]),
                "p25": float(percentiles[1]),
                "p50": float(percentiles[2]),
                "p75": float(percentiles[3]),
                "p98": float(percentiles[4]),
            },
            "histogram": {
                "bin_edges": [float(value) for value in edges],
                "counts": [int(value) for value in counts],
            },
        }

    @staticmethod
    def _color_classes(value):
        """驗證手動色階值嚴格遞增且顏色可由 Qt 解析。"""
        if not isinstance(value, list) or not 2 <= len(value) <= 32:
            raise BridgeError("INVALID_PARAMETERS", "classes 必須包含 2 至 32 個色階。")
        result = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise BridgeError("INVALID_PARAMETERS", "每個 class 必須是 object。")
            raw_number = item.get("value")
            if isinstance(raw_number, bool) or not isinstance(raw_number, (int, float)):
                raise BridgeError("INVALID_PARAMETERS", "class value 必須是有限數值。")
            number = float(raw_number)
            if not math.isfinite(number):
                raise BridgeError("INVALID_PARAMETERS", "class value 必須是有限數值。")
            color = item.get("color")
            if not isinstance(color, str) or not QColor(color).isValid():
                raise BridgeError("INVALID_PARAMETERS", "class color 必須是有效顏色字串。")
            label = item.get("label", str(number))
            if not isinstance(label, str):
                raise BridgeError("INVALID_PARAMETERS", "class label 必須是字串。")
            if index and number <= result[-1]["value"]:
                raise BridgeError("INVALID_PARAMETERS", "class values 必須嚴格遞增且不可重疊。")
            result.append({"value": number, "color": color, "label": label})
        return result

    @staticmethod
    def _temporary_path(output_path, label):
        """建立與最終成果同資料夾、同副檔名的唯一暫存路徑。"""
        return output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex}.{label}{output_path.suffix}")

    @staticmethod
    def _remove_if_exists(path):
        """清除未交付暫存檔；只處理已解析出的單一精確路徑。"""
        with suppress(OSError):
            path.unlink(missing_ok=True)

    @staticmethod
    def _validate_raster_output(path):
        """重新開啟成果，確認至少含一個非空 band。"""
        dataset = gdal.OpenEx(str(path), gdal.OF_RASTER | gdal.OF_READONLY)
        if dataset is None or dataset.RasterCount < 1 or dataset.RasterXSize < 1 or dataset.RasterYSize < 1:
            dataset = None
            raise RuntimeError("Output raster validation failed")
        dataset = None

    @staticmethod
    def _manifest_base(operation, inputs, parameters):
        """建立不含圖徵、像元或秘密的分析成果紀錄。"""
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "operation": operation,
            "plugin_version": PLUGIN_VERSION,
            "inputs": [
                {
                    "layer_id": item["layer_id"],
                    "source": item["source"],
                    "driver": item["driver"],
                    "width": item["width"],
                    "height": item["height"],
                    "crs": item["crs"],
                    "geotransform": item["geotransform"],
                }
                for item in inputs
            ],
            "parameters": parameters,
            "software": {"gdal": gdal.VersionInfo("--version")},
        }

    @staticmethod
    def _write_manifest(output_path, manifest):
        """以同資料夾暫存檔原子寫入 UTF-8 JSON manifest。"""
        manifest_path = Path(f"{output_path}.manifest.json")
        temporary_path = RasterOperations._temporary_path(manifest_path, "manifest")
        try:
            temporary_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_path, manifest_path)
            return manifest_path
        finally:
            RasterOperations._remove_if_exists(temporary_path)
