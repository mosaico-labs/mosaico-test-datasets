"""
Standalone helper functions used by the Mosaico dataset scripts.

These are stateless utilities for discovering dataset folders on disk,
connecting to Mosaico with a profile, and the click options shared by every
bridge's commands. Config loading lives in each bridge (e.g.
:func:`src.ros_bridge.load`).
"""

from pathlib import Path
from typing import Optional

import click
from mosaicolabs import MosaicoClient
from mosaicolabs_cli.utils.mosaico_profile import MosaicoProfile

DATASET_CONFIG_FILENAME = "dataset.toml"


def discover_datasets(base_dir: Path, names: Optional[list[str]] = None) -> list[Path]:
    """Folders under ``base_dir`` holding a ``dataset.toml``, optionally
    restricted to the given folder names (exact, case-sensitive)."""

    datasets = [p for p in base_dir.iterdir() if (p / DATASET_CONFIG_FILENAME).is_file()]
    if names is None:
        return datasets
    return [p for p in datasets if p.name in names]


def connect(profile: MosaicoProfile) -> MosaicoClient:
    """Open a Mosaico client from a resolved profile."""

    return MosaicoClient.connect(
        host=profile.host,
        port=profile.port,
        api_key=profile.api_key,
        enable_tls=profile.enable_tls,
        tls_cert_path=profile.tls_cert_path,
    )


def dataset_options(f):
    """Add the ``DATASETS...``, ``--all`` and ``--n`` options to a command.

    What ``--n`` counts is up to each command, which says so in its help.
    """

    f = click.option(
        "--n",
        type=int,
        default=None,
        help="Process only N items per dataset (see above for which).",
    )(f)
    f = click.option("--all", is_flag=True, help="Use every dataset.")(f)
    return click.argument("datasets", nargs=-1)(f)
