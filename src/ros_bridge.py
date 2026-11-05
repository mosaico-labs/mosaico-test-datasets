"""
ROS bridge for the Mosaico dataset CLI.

Per-dataset configuration (:class:`RosDataset`, read from ``dataset.toml``),
metadata and rosbag discovery, the operations that load, reconstruct and
prune rosbag datasets on Mosaico, and the ``inject`` / ``extract`` /
``delete`` click commands that ``cli.py`` registers under the ``ros`` name.
"""

import json
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import click
from mosaicolabs import SessionLevelErrorPolicy
from mosaicolabs.bridges.ros import (
    RosbagInjector,
    ROSExtractorConfig,
    ROSInjectionConfig,
    ROSSequenceExtractor,
)
from mosaicolabs.bridges.ros.loader import ROSLoader
from mosaicolabs_cli.utils.mosaico_profile import MosaicoProfile
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rosbags.rosbag2 import StoragePlugin
from rosbags.typesys import Stores

from . import BASE_DIR, DATASETS_DIR
from .helper import (
    DATASET_CONFIG_FILENAME,
    connect,
    dataset_options,
    discover_datasets,
)

# Initialize Rich Console for beautiful terminal output
console = Console()


@dataclass
class RosDataset:
    """One ROS dataset, as described by its ``dataset.toml``."""

    bags: Path
    ros_distro: Stores
    topics: list[str] | None = None
    output: Path = Path("/mnt/datasets/bags/reconstructed")
    storage_plugin: StoragePlugin = StoragePlugin.MCAP  # ignored by the SDK for ROS1
    start_ns: int | None = None
    end_ns: int | None = None


def load(folder: Path) -> RosDataset:
    """Read ``folder/dataset.toml``. Any problem raises ValueError naming the file."""

    file = folder / DATASET_CONFIG_FILENAME
    try:
        data = tomllib.loads(file.read_text())
        ds = RosDataset(**data)
        ds.ros_distro = Stores[ds.ros_distro]
        if "storage_plugin" in data:
            ds.storage_plugin = StoragePlugin[ds.storage_plugin]
        # relative paths resolve against the dataset folder; absolute ones pass through
        ds.bags, ds.output = folder / ds.bags, folder / ds.output
        return ds
    except KeyError as e:
        raise ValueError(f"{file.relative_to(BASE_DIR)}: unknown value {e}") from None
    except (OSError, TypeError, ValueError) as e:  # TOMLDecodeError is a ValueError
        raise ValueError(f"{file.relative_to(BASE_DIR)}: {e}") from None


def load_all(names: Optional[list[str]] = None) -> dict[Path, RosDataset]:
    """Load every selected dataset before any server work, reporting all bad files at once."""

    configs, errors = {}, []
    for folder in discover_datasets(DATASETS_DIR, names):
        try:
            configs[folder] = load(folder)
        except ValueError as e:
            errors.append(str(e))
    if errors:
        raise ValueError("bad dataset config(s):\n" + "\n".join(errors))
    return configs


def get_rosbag_paths(bags: Path) -> list[Path]:
    """Find all rosbag files under ``bags``."""

    return [p for p in bags.rglob("*") if p.suffix in ROSLoader.ACCEPTED_EXTENSIONS]


def get_metadata(dataset_path: Path, rosbag_name: str) -> Optional[dict]:
    """Load the JSON metadata associated with a rosbag sequence name."""

    # NOTE: this is only possible beacuse it looks that 1:1 sequence to metadata
    path = dataset_path / "metadata" / f"{rosbag_name}.json"
    if not path.is_file():
        console.print(f"Impossible to find metadata for {rosbag_name} in {path.parent}")
        return None
    return json.loads(path.read_text())


def prune_datasets(
    dataset_to_prune_name: list[str],
    n_bags_to_prune: Optional[int] = None,
) -> None:
    """Delete previously loaded sequences for the given datasets.

    Args:
        dataset_to_prune_name (list[str]): Dataset folder names to prune.
        n_bags_to_prune (int | None): Optional cap on how many loaded
            sequences to delete per dataset. When ``None``, all matching
            sequences are deleted.

    Returns:
        None
    """

    datasets = load_all(dataset_to_prune_name)
    profile = MosaicoProfile.resolve()

    for ds in datasets.values():
        # Sequence names coincide with rosbag names
        rosbag_names_to_prune = [bp.stem for bp in get_rosbag_paths(ds.bags)]

        with connect(profile) as client:
            sequences_to_prune = list(
                set(client.list_sequences()) & set(rosbag_names_to_prune)
            )[:n_bags_to_prune]

            console.print(f"[bold]Pruning {len(sequences_to_prune)} sequences [/bold]")

            for seq in sequences_to_prune:
                console.print(f"[bold]Pruning loaded sequence {seq} [/bold]")
                client.sequence_delete(seq)


def load_datasets(
    datasets_name_to_load: Optional[list[str]] = None,
    n_bags_to_load: Optional[int] = None,
) -> None:
    """Ingest all discovered datasets into Mosaico.

    Args:
        datasets_name_to_load (list[str] | None): Optional whitelist of
            dataset folder names to process. When ``None`` (default) all
            discovered datasets are loaded.
        n_bags_to_load (int | None): Optional number stating how many rosbags
            should be uploaded for each dataset. When ``None``, all rosbags
            for each dataset are loaded.

    Returns:
        None
    """

    datasets = load_all(datasets_name_to_load)
    profile = MosaicoProfile.resolve()

    for dataset_path, ds in datasets.items():
        console.print(
            Panel(
                f"[bold green] Started loading datasets {dataset_path.name} [/bold green]"
            )
        )

        # 1) Getting the rosbags (if present)
        ros_bag_paths = get_rosbag_paths(ds.bags)

        if not ros_bag_paths:
            console.print(
                f"[bold yellow]No rosbags found at path {ds.bags}. Skipping this... [/bold yellow]"
            )
            continue

        # 2) Get already loaded sequences so to avoid loading them again
        with connect(profile) as client:
            all_loaded_sequences = set(client.list_sequences())

        filtered_rosbags = [
            bag_pt
            for bag_pt in ros_bag_paths
            if bag_pt.stem not in all_loaded_sequences
        ][:n_bags_to_load]

        console.print(
            f"[bold green]Loading {len(filtered_rosbags)} from {len(ros_bag_paths)} found bags from {ds.bags} [/bold green]"
        )

        # 3) Injesting rosbags

        # Create statistics table
        table = Table(title="Uploading Rosbag Time Table")

        # Add columns
        table.add_column("Rosbag name", style="magenta")
        table.add_column("Original bag size(Gb)", style="magenta")
        table.add_column("Mosaico sequence size(Gb)", style="magenta")
        table.add_column("Uploading time (s)", style="green")

        loaded_bags = 0
        for bag_path in filtered_rosbags:
            if not bag_path.is_file():
                console.print(
                    f"[bold yellow]{bag_path} is not a rosbag file. Skipping injestion[/bold yellow]"
                )
                continue

            sequence_name = bag_path.stem

            injestor_config = ROSInjectionConfig(
                file_path=bag_path,
                sequence_name=sequence_name,
                metadata=get_metadata(dataset_path, sequence_name) or {},
                host=profile.host,
                port=profile.port,
                log_level="WARNING",
                topics=ds.topics,
                ros_distro=ds.ros_distro,
                on_error=SessionLevelErrorPolicy.Delete,
                mosaico_api_key=profile.api_key,
                enable_tls=profile.enable_tls,
                tls_cert_path=profile.tls_cert_path,
            )

            rosbag_size_mb = bag_path.stat().st_size / (1024 * 1024)
            console.print(
                f"[bold green]Starting ROS injestion {injestor_config.sequence_name} - Size (MB): {rosbag_size_mb:.2f} - bag number {loaded_bags + 1}/{len(filtered_rosbags)} [/bold green]"
            )

            injestor = RosbagInjector(injestor_config)

            try:
                start = time.monotonic()
                injestor.run()
                elapsed_time = time.monotonic() - start

                # Filling statistics table
                with connect(profile) as client:
                    s_hanlder = client.sequence_handler(sequence_name)

                    assert s_hanlder is not None
                    sequence_size_gb = (
                        s_hanlder.total_size_bytes / 1024.0 / 1024.0 / 1024.0
                    )  # Gb

                    table.add_section()
                    table.add_row(
                        sequence_name,  # Rosbag name (coincides with loaded sequence name)
                        f"{(rosbag_size_mb / 1024.0):.2f}",  # Original bag size
                        f"{sequence_size_gb}",  # Mosaico sequence size (if available)
                        f"{elapsed_time}",  # uploading time
                        style=None,
                    )

            except Exception as e:
                console.print(f"[bold red]Injection Failed:[/bold red] {e}")
                continue

            loaded_bags += 1
            console.print(
                f"[bold green]Finished ROS injestion {injestor_config.sequence_name} of {loaded_bags}/{len(filtered_rosbags)} [/bold green]"
            )

        console.print(table)

        console.print(
            Panel(
                f"[bold green]Finished loading datasets {dataset_path.name}[/bold green]"
            )
        )


def unload_datasets(
    datasets_name_to_unload: Optional[list[str]] = None,
    n_sequences: Optional[int] = None,
) -> None:
    """Unload previously ingested datasets from Mosaico.

    Args:
        datasets_name_to_unload (list[str] | None): Optional whitelist of
            dataset folder names to process. When ``None`` (default) all
            discovered datasets are considered.
        n_sequences (int | None): Optional cap on how many sequences to
            unload per dataset. When ``None``, all matching sequences are
            unloaded.

    Returns:
        None
    """

    datasets = load_all(datasets_name_to_unload)
    profile = MosaicoProfile.resolve()

    for dataset_path, ds in datasets.items():
        console.print(
            Panel(
                f"[bold green] Started loading datasets {dataset_path.name} [/bold green]"
            )
        )

        # 1) Getting the rosbags (if present)
        ros_bag_paths = get_rosbag_paths(ds.bags)

        if not ros_bag_paths:
            console.print(
                f"[bold yellow]No rosbags found at path {ds.bags}. Skipping this... [/bold yellow]"
            )
            continue

        filtered_ros_bag_paths = ros_bag_paths[:n_sequences]

        console.print(
            f"[bold green]Loading {len(filtered_ros_bag_paths)} from {len(ros_bag_paths)} found bags from {ds.bags} [/bold green]"
        )

        # Create statistics table
        table = Table(title="Unloading Rosbag Time Table")

        # Add columns
        table.add_column("Rosbag name", style="magenta")
        table.add_column("Mosaico sequence size (Gb)", style="magenta")
        table.add_column("Reconstructed bag size (Gb)", style="magenta")
        table.add_column("Unloading time (s)", style="green")

        unloaded_bags = 0
        for bag_path in filtered_ros_bag_paths:
            if not bag_path.is_file():
                console.print(
                    f"[bold yellow]{bag_path} is not a rosbag file. Skipping rosbag reconstruction[/bold yellow]"
                )
                continue

            sequence_name = bag_path.stem

            ext_configs = ROSExtractorConfig(
                saving_path=ds.output,
                sequence_name=sequence_name,
                host=profile.host,
                port=profile.port,
                ros_distro=ds.ros_distro,
                storage_plugin=ds.storage_plugin,
                topics=ds.topics,
                log_level="WARNING",
                mosaico_api_key=profile.api_key,
                tls_cert_path=profile.tls_cert_path,
                enable_tls=profile.enable_tls,
                start_timestamp_ns=ds.start_ns,
                end_timestamp_ns=ds.end_ns,
                overwrite=True,
            )

            console.print(
                f"[bold green]Starting rosbag reconstruction {ext_configs.sequence_name} - bag number {unloaded_bags + 1}/{len(filtered_ros_bag_paths)} [/bold green]"
            )

            # --- Execution ---
            extractor = ROSSequenceExtractor(ext_configs)

            try:
                start = time.monotonic()
                extractor.run()
                elapsed_time = time.monotonic() - start

                # Filling statistics table
                with connect(profile) as client:
                    s_hanlder = client.sequence_handler(sequence_name)

                    assert s_hanlder is not None
                    sequence_size_gb = (
                        s_hanlder.total_size_bytes / 1024.0 / 1024.0 / 1024.0
                    )  # Gb

                # Whatever extension the SDK's writer picked (.bag / .mcap / .db3)
                reconstructed_bag_file = next(
                    (ds.output / sequence_name).glob(f"{sequence_name}.*")
                )

                reconstructed_size_gb = (
                    reconstructed_bag_file.stat().st_size / 1024.0 / 1024.0 / 1024.0
                )

                table.add_section()
                table.add_row(
                    sequence_name,  # Rosbag name (coincides with unloaded sequence name)
                    f"{sequence_size_gb}",  # Mosaico sequence size
                    f"{reconstructed_size_gb}",  # Reconstructed bag size (on disk)
                    f"{elapsed_time}",  # unloading time
                    style=None,
                )

            except Exception as e:
                console.print(f"[bold red]Extraction Failed:[/bold red] {e}")
                continue

            unloaded_bags += 1
            console.print(
                f"[bold green]Finished rosbag reconstruction {ext_configs.sequence_name} of {unloaded_bags}/{len(filtered_ros_bag_paths)} [/bold green]"
            )

        console.print(table)

        console.print(
            Panel(
                f"[bold green]Finished unloading datasets {dataset_path.name}[/bold green]"
            )
        )


# ---------------------------------------------------------------------------
# Click commands, registered by cli.py as `<verb> ros`
# ---------------------------------------------------------------------------


def _select(datasets: tuple[str, ...], all: bool) -> list[str]:
    """Validate the requested dataset names against the folders on disk."""

    valid = sorted(p.name for p in discover_datasets(DATASETS_DIR))
    if all:
        return valid
    if not datasets:
        raise click.UsageError(
            f"Give dataset names or --all. Valid names: {', '.join(valid)}"
        )
    unknown = [d for d in datasets if d not in valid]
    if unknown:
        raise click.BadParameter(
            f"unknown dataset(s) {', '.join(unknown)}. Valid names: {', '.join(valid)}",
            param_hint="DATASETS",
        )
    return list(datasets)


def _run(fn, *args) -> None:
    """Run an operation, turning any failure into a clean exit code 1."""

    try:
        fn(*args)
    except Exception as e:
        raise click.ClickException(str(e)) from e


@click.command()
@dataset_options
def inject(datasets, all, n):
    """Inject rosbag datasets into Mosaico.

    --n N injects the first N bags of each dataset not yet on the server.
    """
    _run(load_datasets, _select(datasets, all), n)


@click.command()
@dataset_options
def extract(datasets, all, n):
    """Reconstruct rosbags from the sequences stored in Mosaico.

    --n N reconstructs the first N bags of each dataset.
    """
    _run(unload_datasets, _select(datasets, all), n)


@click.command()
@dataset_options
def delete(datasets, all, n):
    """Delete a dataset's sequences from Mosaico.

    --n N deletes up to N of each dataset's sequences on the server.
    """
    _run(prune_datasets, _select(datasets, all), n)
