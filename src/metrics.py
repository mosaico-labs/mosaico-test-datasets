"""
Structured metrics output for the Mosaico dataset scripts.

The scripts print their statistics as Rich tables, which are meant for humans.
:class:`MetricsRecorder` collects the same numbers as plain records and writes
them to a JSON file, so that other tools (e.g. the Mr. Coffee performance bot)
can consume them.

The file is rewritten atomically after every record, so a reader polling it
always sees a valid JSON document with the bags processed so far.
"""

import json
import os
import platform
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .upload_timing import UploadTiming

MB = 1024.0**2


def upload_timing_to_dict(timing: UploadTiming) -> dict[str, Any]:
    """Convert an :class:`UploadTiming` to a dict, including derived values.

    Args:
        timing (UploadTiming): Timing breakdown of a single upload.

    Returns:
        dict[str, Any]: All fields plus ``server_s``, ``python_s`` and ``sdk_s``.
    """

    data = asdict(timing)
    data["server_s"] = timing.server_s
    data["python_s"] = timing.python_s
    data["sdk_s"] = timing.sdk_s
    return data


class MetricsRecorder:
    """Collect per-bag records and write them to a JSON file.

    When ``path`` is ``None`` every method is a no-op, so callers do not need
    to check whether metrics output was requested.

    Args:
        path (str | Path | None): Destination JSON file.
        operation (str): Name of the operation, e.g. ``"ingest"``.
    """

    def __init__(self, path: Optional[str | Path], operation: str):
        self.path = Path(path) if path is not None else None
        self.document: dict[str, Any] = {
            "operation": operation,
            "started_at": time.time(),
            "finished_at": None,
            "host": platform.node(),
            "machine": platform.machine(),
            "bags": [],
        }
        self._flush()

    def add_bag(self, dataset: str, sequence_name: str, **values: Any) -> None:
        """Append the record of a processed bag and rewrite the file.

        Args:
            dataset (str): Dataset folder name.
            sequence_name (str): Rosbag / sequence name.
            **values: Metrics of the bag (sizes, timings, status, error...).
        """

        self.document["bags"].append(
            {"dataset": dataset, "sequence": sequence_name, **values}
        )
        self._flush()

    def finish(self) -> None:
        """Mark the operation as finished and rewrite the file."""

        self.document["finished_at"] = time.time()
        self._flush()

    def _flush(self) -> None:
        if self.path is None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(self.document, f, indent=2)
        os.replace(tmp_path, self.path)
