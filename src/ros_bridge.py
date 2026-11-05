"""
ROS bridge for the Mosaico dataset CLI.

Per-dataset configuration, metadata and rosbag discovery
(:class:`RosbagHandler`), the operations that load, reconstruct and prune
rosbag datasets on Mosaico, and the ``inject`` / ``extract`` / ``delete``
click commands that ``cli.py`` registers under the ``ros`` name.
"""

import importlib.util
import json
import time
from pathlib import Path
from typing import Any, Optional

import click
from mosaicolabs import MosaicoClient, SessionLevelErrorPolicy
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

from .helper import (
    DATASET_CONFIG_FILENAME,
    dataset_options,
    discover_datasets,
    get_name_from_rosbag,
)

# Initialize Rich Console for beautiful terminal output
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
        "PATH_TO_BAGS",
        "ROS_DISTRO",
        "TOPICS_TO_FILTER",
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


BASE_DIR = Path(__file__).resolve().parent
DATASETS_DIR = BASE_DIR / "Datasets" / "ros"


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

    global_configs = load_global_config(BASE_DIR)
    profile = MosaicoProfile.resolve()

    dataset_to_prune_paths_ = discover_datasets(DATASETS_DIR, dataset_to_prune_name)

    if not dataset_to_prune_paths_:
        console.print(
            f"[bold red] Impossible to prune {dataset_to_prune_name}. These are not valid dataset names[/bold red]"
        )

    for dt_path in dataset_to_prune_paths_:
        handler = RosbagHandler(dt_path, global_configs)
        configs = handler.config

        if configs is None:
            console.print(
                f"[bold red]Failed loading dataset {dt_path}. Are you sure there is a config.py file? [/bold red]"
            )
            continue

        # Sequence names coincide with rosbag names
        rosbag_names_to_prune = [
            get_name_from_rosbag(bp) for bp in handler.get_rosbag_paths()
        ]

        with MosaicoClient.connect(
            host=profile.host,
            port=profile.port,
            api_key=profile.api_key,
            enable_tls=profile.enable_tls,
            tls_cert_path=profile.tls_cert_path,
        ) as client:
            all_loaded_sequences = client.list_sequences()

            sequences_to_prune = list(
                set(all_loaded_sequences) & set(rosbag_names_to_prune)
            )

            if n_bags_to_prune is not None:
                sequences_to_prune = sequences_to_prune[:n_bags_to_prune]

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

    global_configs = load_global_config(BASE_DIR)
    profile = MosaicoProfile.resolve()

    dataset_to_load_paths_ = discover_datasets(DATASETS_DIR, datasets_name_to_load)

    for dataset_path in dataset_to_load_paths_:
        console.print(
            Panel(
                f"[bold green] Started loading datasets {dataset_path.name} [/bold green]"
            )
        )

        # 0) overriding default configuration for dataset loading
        handler = RosbagHandler(dataset_path, global_configs)
        configs = handler.config

        # 1) Getting the rosbags (if present)
        ros_bag_paths = handler.get_rosbag_paths()

        if not ros_bag_paths:
            console.print(
                f"[bold yellow]No rosbags found at path {configs['PATH_TO_BAGS']}. Skipping this... [/bold yellow]"
            )
            continue

        # 2) Get already loaded sequences so to avoid loading them again
        all_loaded_sequences = []
        with MosaicoClient.connect(
            host=profile.host,
            port=profile.port,
            api_key=profile.api_key,
            enable_tls=profile.enable_tls,
            tls_cert_path=profile.tls_cert_path,
        ) as client:
            all_loaded_sequences.extend(client.list_sequences())

        filtered_rosbags = [
            bag_pt
            for bag_pt in ros_bag_paths
            if get_name_from_rosbag(bag_pt) not in all_loaded_sequences
        ]

        if n_bags_to_load is not None:
            filtered_rosbags = filtered_rosbags[:n_bags_to_load]

        console.print(
            f"[bold green]Loading {len(filtered_rosbags)} from {len(ros_bag_paths)} found bags from {configs['PATH_TO_BAGS']} [/bold green]"
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

            sequence_name = get_name_from_rosbag(bag_path)

            injestor_config = ROSInjectionConfig(
                file_path=bag_path,
                sequence_name=sequence_name,
                metadata=handler.get_metadata(sequence_name) or {},
                host=profile.host,
                port=profile.port,
                log_level="WARNING",
                topics=configs["TOPICS_TO_FILTER"],
                ros_distro=configs["ROS_DISTRO"],
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
                with MosaicoClient.connect(
                    host=profile.host,
                    port=profile.port,
                    api_key=profile.api_key,
                    enable_tls=profile.enable_tls,
                    tls_cert_path=profile.tls_cert_path,
                ) as client:
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

    global_configs = load_global_config(BASE_DIR)
    profile = MosaicoProfile.resolve()

    dataset_to_load_paths_ = discover_datasets(DATASETS_DIR, datasets_name_to_unload)

    for dataset_path in dataset_to_load_paths_:
        console.print(
            Panel(
                f"[bold green] Started loading datasets {dataset_path.name} [/bold green]"
            )
        )

        # 0) overriding default configuration for dataset loading
        handler = RosbagHandler(dataset_path, global_configs)
        configs = handler.config

        # 1) Getting the rosbags (if present)
        ros_bag_paths = handler.get_rosbag_paths()

        if not ros_bag_paths:
            console.print(
                f"[bold yellow]No rosbags found at path {configs['PATH_TO_BAGS']}. Skipping this... [/bold yellow]"
            )
            continue

        if n_sequences is not None:
            filtered_ros_bag_paths = ros_bag_paths[:n_sequences]
        else:
            filtered_ros_bag_paths = ros_bag_paths

        console.print(
            f"[bold green]Loading {len(filtered_ros_bag_paths)} from {len(ros_bag_paths)} found bags from {configs['PATH_TO_BAGS']} [/bold green]"
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

            # Strip final file from bag_path
            sequence_name = get_name_from_rosbag(bag_path)

            ext_configs = ROSExtractorConfig(
                saving_path=Path(configs["PATH_TO_RECONSTRUCTED_BAGS"]),
                sequence_name=sequence_name,
                host=profile.host,
                port=profile.port,
                ros_distro=configs["ROS_DISTRO"],
                storage_plugin=configs["STORAGE_PLUGIN"],
                topics=configs["TOPICS_TO_FILTER"],
                log_level="WARNING",
                mosaico_api_key=profile.api_key,
                tls_cert_path=profile.tls_cert_path,
                enable_tls=profile.enable_tls,
                start_timestamp_ns=configs["START_TIMESTAMP_NS"],
                end_timestamp_ns=configs["END_TIMESTAMP_NS"],
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

                with MosaicoClient.connect(
                    host=profile.host,
                    port=profile.port,
                    api_key=profile.api_key,
                    enable_tls=profile.enable_tls,
                    tls_cert_path=profile.tls_cert_path,
                ) as client:
                    s_hanlder = client.sequence_handler(sequence_name)

                    assert s_hanlder is not None
                    sequence_size_gb = (
                        s_hanlder.total_size_bytes / 1024.0 / 1024.0 / 1024.0
                    )  # Gb

                if configs["STORAGE_PLUGIN"] is StoragePlugin.MCAP:
                    bag_extension = ".mcap"
                elif configs["STORAGE_PLUGIN"] is StoragePlugin.SQLITE3:
                    bag_extension = ".db3"
                else:
                    bag_extension = ".bag"

                reconstructed_bag_file = (
                    Path(configs["PATH_TO_RECONSTRUCTED_BAGS"])
                    / sequence_name
                    / (sequence_name + bag_extension)
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
