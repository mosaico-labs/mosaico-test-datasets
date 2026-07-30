"""
Per-dataset configuration, metadata and rosbag discovery for the Mosaico
dataset scripts.

The :class:`RosbagHandler` bundles the concerns that are specific to a
single dataset directory: merging its ``configs.py`` on top of the global
defaults, resolving where its rosbags live, and loading the JSON metadata
associated with a given rosbag sequence.
"""

import importlib.util
import json
from pathlib import Path
from typing import Any, Optional

from mosaicolabs.ros_bridge.loader import ROSLoader
from rich.console import Console

from .helper import DATASET_CONFIG_FILENAME

console = Console()


class RosbagHandler:
    """Resolves configuration, metadata and rosbag paths for one dataset.

    A handler is bound to a single dataset directory (the folder holding
    that dataset's ``configs.py`` and ``metadata/``). Where to look for the
    actual rosbag files is optional: pass ``rosbags_path`` to search a
    specific directory, or omit it to fall back to the dataset's configured
    ``PATH_TO_BAGS`` (and, failing that, the dataset directory itself).
    """

    DATASET_CONFIG_FILENAME = DATASET_CONFIG_FILENAME

    CONFIG_KEY_NAMES = [
        "MOSAICO_HOST",
        "MOSAICO_PORT",
        "PATH_TO_BAGS",
        "ROS_DISTRO",
        "TOPICS_TO_FILTER",
        "API_KEY",
        "ENABLE_TLS",
        "TLS_CERT_PATH",
        "PATH_TO_RECONSTRUCTED_BAGS",
        "STORAGE_PLUGIN",
        "START_TIMESTAMP_NS",
        "END_TIMESTAMP_NS",
    ]

    def __init__(
        self,
        dataset_path: Path,
        global_configs: dict[str, str],
    ):
        """Initialise the handler and eagerly resolve its configuration.

        Args:
            dataset_path (Path): Directory holding this dataset's
                ``configs.py`` and ``metadata/`` folder.
            global_configs (dict[str, str]): Global default configuration to
                use as a base, overridden by the dataset's own ``configs.py``.
        """

        self.dataset_path = dataset_path
        self.global_configs = global_configs
        self.config = self._load_config()

        if self.config["PATH_TO_BAGS"]:
            self.rosbags_path = Path(self.config["PATH_TO_BAGS"])

    def _get_config_module(self):
        """Dynamically load this dataset's ``configs.py`` as a Python module.

        Returns:
            types.ModuleType | None: The loaded module object, or ``None``
            if no ``configs.py`` could be found at ``dataset_path``.
        """

        spec = importlib.util.spec_from_file_location(
            "cfg", self.dataset_path / self.DATASET_CONFIG_FILENAME
        )

        if spec is None:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module

    def _load_config(self) -> dict[str, Any]:
        """Merge the global defaults with this dataset's config overrides.

        Returns:
            dict[str, Any] | None: Merged configuration dictionary, or
            ``None`` if the ``configs.py`` module could not be loaded.
        """

        config = {key: value for key, value in self.global_configs.items()}

        module = self._get_config_module()
        if module is None:
            raise ModuleNotFoundError(
                f"Could not load {self.dataset_path / self.DATASET_CONFIG_FILENAME} module. Does it exist?"
            )

        for cfg_key in self.CONFIG_KEY_NAMES:
            if hasattr(module, cfg_key):
                config[cfg_key] = getattr(module, cfg_key)

        # Check that computed config dict contains all the necessary keys
        if not all(mandatory_key in config for mandatory_key in self.CONFIG_KEY_NAMES):
            raise KeyError(
                f"Not all key are present within loaded config dict. Currently present keys are: {config.keys()}, while expected keys are f{self.CONFIG_KEY_NAMES}"
            )

        return config

    def get_rosbag_paths(self) -> list[Path]:
        """Find all rosbag files under ``self.rosbags_path``."""

        return [
            bp
            for ext in ROSLoader.ACCEPTED_EXTENSIONS
            for bp in self.rosbags_path.rglob(f"*{ext}")
        ]

    def get_metadata(self, rosbag_name: str) -> Optional[dict]:
        """Load the JSON metadata associated with a rosbag sequence name."""

        path_to_dataset_metadata = self.dataset_path / "metadata"

        rosbag_metadata_path = next(
            (
                mtp
                for mtp in path_to_dataset_metadata.glob("*.json")
                if mtp.name.removesuffix(".json") == rosbag_name
            ),
            None,
        )

        if rosbag_metadata_path is None or not rosbag_metadata_path.exists():
            console.print(
                f"Impossible to find metadata for {rosbag_name} in {path_to_dataset_metadata}"
            )
            return None

        with open(rosbag_metadata_path) as f:
            return json.load(f)


def load_global_config(base_dir: Path) -> dict[str, Any]:
    """Load the global default configuration from ``base_dir/configs.py``."""

    return RosbagHandler(base_dir, global_configs={}).config or {}
