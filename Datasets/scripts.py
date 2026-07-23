"""
Scripts for the Mosaico dataset loader CLI.

This module contains the top-level operations invoked from ``cli.py``:
loading rosbag datasets into Mosaico, pruning previously loaded sequences,
and (eventually) unloading them. Dataset discovery lives in ``helper.py``;
per-dataset configuration and metadata retrieval live in
``rosbag_handler.RosbagHandler``.
"""

# Mosaico SDK Imports
from mosaicolabs import SessionLevelErrorPolicy, MosaicoClient
from mosaicolabs.ros_bridge import RosbagInjector, ROSInjectionConfig
from mosaicolabs.ros_bridge import ROSExtractorConfig, ROSSequenceExtractor

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from .helper import discover_datasets, get_name_from_rosbag
from .rosbag_handler import RosbagHandler, load_global_config


# Initialize Rich Console for beautiful terminal output
console = Console()

BASE_DIR = Path(__file__).resolve().parent


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

    dataset_to_prune_paths_ = discover_datasets(BASE_DIR, dataset_to_prune_name)

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
            host=configs["MOSAICO_HOST"],
            port=configs["MOSAICO_PORT"],
            api_key=configs["API_KEY"],
            enable_tls=configs["ENABLE_TLS"],
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

    dataset_to_load_paths_ = discover_datasets(BASE_DIR, datasets_name_to_load)

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
            host=configs["MOSAICO_HOST"],
            port=configs["MOSAICO_PORT"],
            api_key=configs["API_KEY"],
            enable_tls=configs["ENABLE_TLS"],
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
                host=configs["MOSAICO_HOST"],
                port=configs["MOSAICO_PORT"],
                log_level="WARNING",
                topics=configs["TOPICS_TO_FILTER"],
                ros_distro=configs["ROS_DISTRO"],
                on_error=SessionLevelErrorPolicy.Delete,
                mosaico_api_key=configs["API_KEY"],
                enable_tls=configs["ENABLE_TLS"],
                tls_cert_path=configs["TLS_CERT_PATH"],
            )

            console.print(
                f"[bold green]Starting ROS injestion {injestor_config.sequence_name} - Size (MB): {bag_path.stat().st_size / (1024 * 1024):.2f} - bag number {loaded_bags + 1}/{len(filtered_rosbags)} [/bold green]"
            )

            injestor = RosbagInjector(injestor_config)

            try:
                injestor.run()
            except Exception as e:
                console.print(f"[bold red]Injection Failed:[/bold red] {e}")
                continue

            loaded_bags += 1
            console.print(
                f"[bold green]Finished ROS injestion {injestor_config.sequence_name} of {loaded_bags}/{len(filtered_rosbags)} [/bold green]"
            )

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

    dataset_to_load_paths_ = discover_datasets(BASE_DIR, datasets_name_to_unload)

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

        unloaded_bags = 0
        for bag_path in filtered_ros_bag_paths:
            if not bag_path.is_file():
                console.print(
                    f"[bold yellow]{bag_path} is not a rosbag file. Skipping rosbag reconstruction[/bold yellow]"
                )
                continue

            # Strip final file from bag_path
            folder_bag_path = bag_path.parent

            sequence_name = get_name_from_rosbag(bag_path)

            ext_configs = ROSExtractorConfig(
                rosbag_path=folder_bag_path,
                sequence_name=sequence_name,
                host=configs["MOSAICO_HOST"],
                port=configs["MOSAICO_PORT"],
                ros_distro=configs["ROS_DISTRO"],
                storage_plugin=configs["STORAGE_PLUGIN"],
                topics=configs["TOPICS_TO_FILTER"],
                log_level="WARNING",
                mosaico_api_key=configs["API_KEY"],
                tls_cert_path=configs["TLS_CERT_PATH"],
                enable_tls=configs["ENABLE_TLS"],
                start_timestamp_ns=configs["START_TIMESTAMP_NS"],
                end_timestamp_ns=configs["END_TIMESTAMP_NS"],
                overwrite=True,
            )

            console.print(
                f"[bold green]Starting rosbag reconstruction {ext_configs.sequence_name} - bag number {unloaded_bags + 1}/{len(filtered_ros_bag_paths)} [/bold green]"
            )

            # --- Execution ---
            extractor = ROSSequenceExtractor(ext_configs)
            extractor.run()

            unloaded_bags += 1
            console.print(
                f"[bold green]Finished rosbag reconstruction {ext_configs.sequence_name} of {unloaded_bags}/{len(filtered_ros_bag_paths)} [/bold green]"
            )

        console.print(
            Panel(
                f"[bold green]Finished unloading datasets {dataset_path.name}[/bold green]"
            )
        )
