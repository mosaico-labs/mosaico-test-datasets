"""
Standalone helper functions used by the Mosaico dataset scripts.

These are stateless utilities for discovering dataset folders on disk and
deriving names from rosbag files. Config loading and metadata retrieval live
in :class:`~Datasets.rosbag_handler.RosbagHandler` instead, since they carry
per-dataset state.
"""

from pathlib import Path
from typing import Optional

DATASET_CONFIG_FILENAME = "configs.py"


def is_valid_dataset(
    path_to_dataset: Path, config_filename: str = DATASET_CONFIG_FILENAME
) -> bool:
    """Check whether a path represents a valid dataset directory.

    A path is considered a valid dataset when it is a directory **and**
    it contains a ``configs.py`` file (the file may be empty).

    Args:
        path_to_dataset (Path): Filesystem path to evaluate.
        config_filename (str): Name of the per-dataset config file to look for.

    Returns:
        bool: ``True`` if the path is a directory containing the config
        file, ``False`` otherwise.
    """

    return path_to_dataset.is_dir() and (path_to_dataset / config_filename).is_file()


def discover_datasets(
    base_dir: Path,
    dataset_names_to_load: Optional[list[str]] = None,
    config_filename: str = DATASET_CONFIG_FILENAME,
) -> list[Path]:
    """Discover all valid dataset directories under ``base_dir``.

    Args:
        base_dir (Path): Root directory to search for dataset folders.
        dataset_names_to_load (list[str] | None): Optional whitelist of
            folder names. Folder names must match exactly (case-sensitive).
            Pass ``None`` to return all discovered datasets.
        config_filename (str): Name of the per-dataset config file to look for.

    Returns:
        list[Path]: Paths to the discovered (and optionally filtered)
        dataset directories.
    """

    all_datasets = [
        entry
        for entry in base_dir.iterdir()
        if is_valid_dataset(entry, config_filename)
    ]

    if dataset_names_to_load is None:
        return all_datasets

    # Filtering accordingly to the passed datasets to load.
    # Notice that to filter effectively, the passed dataset names
    # need to coincide with the folder names
    return [dt_path for dt_path in all_datasets if dt_path.name in dataset_names_to_load]


def get_name_from_rosbag(rosbag_path: Path) -> str:
    """Derive the sequence name from a rosbag file path (its stem)."""

    return rosbag_path.with_suffix("").name
