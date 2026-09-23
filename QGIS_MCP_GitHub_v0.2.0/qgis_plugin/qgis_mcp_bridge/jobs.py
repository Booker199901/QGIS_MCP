"""管理可查詢、可取消且不阻塞 HTTP 回應的 QGIS Processing 工作。"""

import time
import uuid
from functools import partial

from qgis.core import (
    QgsApplication,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingUtils,
    QgsProject,
    QgsRasterLayer,
    QgsTask,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QObject, QTimer

from .constants import JOB_RETENTION_SECONDS
from .errors import BridgeError
from .utils import redact_sensitive_text, redact_sensitive_value


class _CallableTask(QgsTask):
    """在背景執行只接收純資料的受控工作，並保存有限結果。"""

    def __init__(self, description, worker):
        task_flags = getattr(QgsTask, "Flag", QgsTask)
        can_cancel = task_flags.CanCancel
        super().__init__(description, can_cancel)
        self.worker = worker
        self.result_value = None
        self.error_value = None

    def run(self):
        """執行工作；例外留在工作紀錄，由主執行緒轉成安全錯誤。"""
        try:
            self.result_value = self.worker(self)
            return not self.isCanceled()
        except Exception as error:  # noqa: BLE001 - 背景 task 邊界必須保存所有失敗。
            self.error_value = error
            return False


class JobManager(QObject):
    """保存 task、context 與 feedback，確保其生命週期長於背景工作。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs = {}  # 已完成工作保留有限時間，供斷線後重新取得結果。
        self._queue = []  # 同一 QGIS 實例的 Processing 依序執行，避免同時寫入專案。
        self._active_job_id = None

    def start_processing(
        self,
        algorithm,
        parameters,
        add_outputs_to_project,
        result_transform=None,
        result_metadata=None,
    ):
        """複製演算法、建立 context/feedback 並交由全域 QgsTaskManager 執行。"""
        self._cleanup_expired()
        algorithm_instance = algorithm.create()
        if algorithm_instance is None:
            raise BridgeError("PROCESSING_FAILED", "無法建立 Processing 演算法執行個體。")
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        feedback = QgsProcessingFeedback()
        task = QgsProcessingAlgRunnerTask(algorithm_instance, parameters, context, feedback)
        job_id = str(uuid.uuid4())
        now = time.time()
        record = {
            "job_id": job_id,
            "algorithm_id": algorithm.id(),
            "status": "queued",
            "progress": 0.0,
            "progress_text": "",
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
            "warnings": [],
            "task": task,
            "context": context,
            "feedback": feedback,
            "add_outputs_to_project": bool(add_outputs_to_project),
            "result_transform": result_transform,
            "result_metadata": result_metadata or {},
            "job_type": "processing",
        }
        self._jobs[job_id] = record
        task.begun.connect(partial(self._on_begun, job_id))
        task.progressChanged.connect(partial(self._on_progress, job_id))
        progress_text_changed = getattr(feedback, "progressTextChanged", None)
        if progress_text_changed is not None:
            progress_text_changed.connect(partial(self._on_progress_text, job_id))
        task.executed.connect(partial(self._on_finished, job_id))
        self._queue.append(job_id)
        self._start_next()
        return self._public_record(record)

    def start_callable(self, description, worker, job_type, add_outputs_to_project, result_metadata=None):
        """將 GDAL 等不碰觸 QGIS GUI 物件的工作放入相同序列佇列。"""
        self._cleanup_expired()
        task = _CallableTask(description, worker)
        job_id = str(uuid.uuid4())
        now = time.time()
        record = {
            "job_id": job_id,
            "algorithm_id": job_type,
            "status": "queued",
            "progress": 0.0,
            "progress_text": "",
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
            "warnings": [],
            "task": task,
            "context": None,
            "feedback": None,
            "add_outputs_to_project": bool(add_outputs_to_project),
            "result_transform": None,
            "result_metadata": result_metadata or {},
            "job_type": job_type,
        }
        self._jobs[job_id] = record
        task.begun.connect(partial(self._on_begun, job_id))
        task.progressChanged.connect(partial(self._on_progress, job_id))
        task.taskCompleted.connect(partial(self._on_callable_finished, job_id, True))
        task.taskTerminated.connect(partial(self._on_callable_finished, job_id, False))
        self._queue.append(job_id)
        self._start_next()
        return self._public_record(record)

    def _start_next(self):
        """僅在沒有執行中工作時，將下一筆排入 QGIS Task Manager。"""
        if self._active_job_id is not None:
            return
        while self._queue:
            job_id = self._queue.pop(0)
            record = self._jobs.get(job_id)
            if record is None or record["status"] != "queued":
                continue
            self._active_job_id = job_id
            QgsApplication.taskManager().addTask(record["task"])
            return

    def _on_begun(self, job_id):
        """由 QGIS 主執行緒把工作狀態切為 running。"""
        record = self._jobs.get(job_id)
        if record is not None:
            record["status"] = "running"
            record["started_at"] = time.time()

    def _on_progress(self, job_id, progress):
        """保存底層演算法實際提供的 0–100 進度。"""
        record = self._jobs.get(job_id)
        if record is not None:
            record["progress"] = max(0.0, min(100.0, float(progress)))

    def _on_progress_text(self, job_id, text):
        """保存簡短進度文字，不把完整 provider log 無限制回傳。"""
        record = self._jobs.get(job_id)
        if record is not None:
            record["progress_text"] = str(text)[:1000]

    def _on_finished(self, job_id, successful, results):
        """在主執行緒接管暫存圖層並保存結果；參照保留到紀錄過期。"""
        record = self._jobs.get(job_id)
        if record is None:
            return
        record["finished_at"] = time.time()
        feedback = record["feedback"]
        task = record["task"]
        if task.isCanceled() or feedback.isCanceled():
            record["status"] = "cancelled"
            record["error"] = {"code": "CANCELLED", "message": "工作已取消。"}
        elif not successful:
            record["status"] = "failed"
            log_text = redact_sensitive_text(feedback.textLog()[-4000:])
            record["error"] = {
                "code": "PROCESSING_FAILED",
                "message": "Processing 演算法執行失敗。",
                "details": {"feedback_tail": log_text},
            }
        else:
            transform = record.get("result_transform")
            if transform is not None:
                try:
                    results = transform(results)
                except Exception as error:  # noqa: BLE001 - 將 finalize 失敗轉成工作失敗。
                    record["status"] = "failed"
                    record["error"] = {
                        "code": "PROCESSING_FAILED",
                        "message": "成果完成處理失敗。",
                        "details": {"error": redact_sensitive_text(error)},
                    }
                    self._finish_active(job_id)
                    return
            added_layers = []
            if record["add_outputs_to_project"]:
                added_layers = self._add_result_layers(record["context"], results)
            record["status"] = "completed"
            record["progress"] = 100.0
            record["result"] = {
                "algorithm_id": record["algorithm_id"],
                "outputs": redact_sensitive_value(results),
                "added_layers": added_layers,
                "feedback_tail": redact_sensitive_text(feedback.textLog()[-4000:]),
                "metadata": redact_sensitive_value(record.get("result_metadata", {})),
            }
        # QGIS 官方要求 task 執行期間 context 與 feedback 必須持續存活。executed
        # signal 發出時，Task Manager 仍可能尚未完成內部收尾，因此不在 callback
        # 立刻釋放 QObject；統一由 _cleanup_expired 移除整筆紀錄最安全。
        self._finish_active(job_id)

    def _on_callable_finished(self, job_id, successful, *_args):
        """在主執行緒收尾背景 GDAL 工作並加入已完成的輸出圖層。"""
        record = self._jobs.get(job_id)
        if record is None or record["finished_at"] is not None:
            return
        record["finished_at"] = time.time()
        task = record["task"]
        if task.isCanceled():
            record["status"] = "cancelled"
            record["error"] = {"code": "CANCELLED", "message": "工作已取消，未交付部分成果。"}
        elif not successful or task.error_value is not None:
            record["status"] = "failed"
            record["error"] = {
                "code": "PROCESSING_FAILED",
                "message": "背景地理處理工作失敗。",
                "details": {"error": redact_sensitive_text(task.error_value or "task terminated")},
            }
        else:
            result = (
                task.result_value
                if isinstance(task.result_value, dict)
                else {"value": task.result_value}
            )
            warnings = result.pop("warnings", [])
            layer_paths = result.pop("layer_paths", [])
            added_layers = []
            if record["add_outputs_to_project"]:
                added_layers = self._add_external_layers(layer_paths)
            record["warnings"] = [str(item)[:1000] for item in warnings[:100]]
            record["status"] = "completed"
            record["progress"] = 100.0
            record["result"] = {
                **redact_sensitive_value(result),
                "added_layers": added_layers,
                "metadata": redact_sensitive_value(record.get("result_metadata", {})),
            }
        self._finish_active(job_id)

    def _finish_active(self, job_id):
        """釋放目前佇列位置並在下一個 event-loop tick 啟動後續工作。"""
        if self._active_job_id == job_id:
            self._active_job_id = None
        QTimer.singleShot(0, self._start_next)

    @staticmethod
    def _add_result_layers(context, results):
        """只在完成 callback 的主執行緒安全接管有效地圖圖層。"""
        project = QgsProject.instance()
        added_layers = []
        seen_layer_ids = set()
        for value in results.values():
            if not isinstance(value, str) or not value:
                continue
            layer = context.getMapLayer(value)
            if layer is None:
                layer = QgsProcessingUtils.mapLayerFromString(value, context, True)
            if layer is None or not layer.isValid() or layer.id() in seen_layer_ids:
                continue
            seen_layer_ids.add(layer.id())
            if project.mapLayer(layer.id()) is None:
                owned_layer = context.takeResultLayer(layer.id())
                project.addMapLayer(owned_layer or layer)
            added_layers.append({"layer_id": layer.id(), "name": layer.name()})
        return added_layers

    @staticmethod
    def _add_external_layers(paths):
        """只在主執行緒將背景工作已完成的本機成果加入專案。"""
        project = QgsProject.instance()
        added_layers = []
        for path in paths:
            if not isinstance(path, str) or not path:
                continue
            name = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
            layer = QgsRasterLayer(path, name, "gdal")
            if not layer.isValid():
                layer = QgsVectorLayer(path, name, "ogr")
            if not layer.isValid():
                continue
            project.addMapLayer(layer)
            added_layers.append({"layer_id": layer.id(), "name": layer.name()})
        return added_layers

    def get_status(self, job_id):
        """取得工作狀態；未知或過期 ID 不會指向其他工作。"""
        self._cleanup_expired()
        record = self._jobs.get(job_id)
        if record is None:
            raise BridgeError("JOB_NOT_FOUND", f"找不到工作：{job_id}")
        return self._public_record(record)

    def get_result(self, job_id):
        """回傳已完成結果，執行中則仍只提供公開狀態。"""
        return self.get_status(job_id)

    def cancel(self, job_id):
        """要求 QgsTask 取消並據實回報取消請求是否送出。"""
        record = self._jobs.get(job_id)
        if record is None:
            raise BridgeError("JOB_NOT_FOUND", f"找不到工作：{job_id}")
        if record["status"] in {"completed", "failed", "cancelled"}:
            return self._public_record(record)
        if record["status"] == "queued" and job_id in self._queue:
            self._queue.remove(job_id)
            record["status"] = "cancelled"
            record["finished_at"] = time.time()
            record["error"] = {"code": "CANCELLED", "message": "排隊中的工作已取消。"}
            return self._public_record(record)
        task = record["task"]
        if task is None:
            raise BridgeError("CANCEL_NOT_SUPPORTED", "工作目前無法取消。")
        task.cancel()
        record["status"] = "cancelling"
        record["progress_text"] = "Cancellation requested; waiting for the worker to stop"
        return self._public_record(record)

    @staticmethod
    def _public_record(record):
        """移除 QObject 與內部 context 後回傳 JSON 相容工作資料。"""
        return {
            "job_id": record["job_id"],
            "algorithm_id": record["algorithm_id"],
            "job_type": record.get("job_type", "processing"),
            "status": record["status"],
            "progress": record["progress"],
            "progress_text": record["progress_text"],
            "created_at": record["created_at"],
            "started_at": record["started_at"],
            "finished_at": record["finished_at"],
            "result": record["result"],
            "error": record["error"],
            "warnings": record["warnings"],
        }

    def _cleanup_expired(self):
        """只移除完成超過保留時間的記憶體紀錄，不刪除任何成果檔。"""
        cutoff = time.time() - JOB_RETENTION_SECONDS
        expired_ids = [
            job_id
            for job_id, record in self._jobs.items()
            if record["finished_at"] is not None and record["finished_at"] < cutoff
        ]
        for job_id in expired_ids:
            self._jobs.pop(job_id, None)
