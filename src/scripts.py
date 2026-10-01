"""
Scripts for the Mosaico dataset loader CLI.

This module contains the top-level operations invoked from ``cli.py``:
loading rosbag datasets into Mosaico, pruning previously loaded sequences,
and (eventually) unloading them. Dataset discovery lives in ``helper.py``;
per-dataset configuration and metadata retrieval live in
``rosbag_handler.RosbagHandler``.
"""

# Mosaico SDK Imports
import signal
import time
from pathlib import Path
from typing import Optional

from mosaicolabs import MosaicoClient, SequenceDataStreamer, SessionLevelErrorPolicy
from mosaicolabs.ros_bridge import (
    RosbagInjector,
    ROSExtractorConfig,
    ROSInjectionConfig,
    ROSSequenceExtractor,
)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rosbags.rosbag2 import StoragePlugin

from .helper import discover_datasets, get_name_from_rosbag
from .rosbag_handler import RosbagHandler, load_global_config
from .upload_timing import measure_upload

# Initialize Rich Console for beautiful terminal output
console = Console()

BASE_DIR = Path(__file__).resolve().parent
DATASETS_DIR = BASE_DIR / "Datasets"


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
            host=configs["MOSAICO_HOST"],
            port=configs["MOSAICO_PORT"],
            api_key=configs["API_KEY"],
            enable_tls=configs["ENABLE_TLS"],
            tls_cert_path=configs["TLS_CERT_PATH"],
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
            host=configs["MOSAICO_HOST"],
            port=configs["MOSAICO_PORT"],
            api_key=configs["API_KEY"],
            enable_tls=configs["ENABLE_TLS"],
            tls_cert_path=configs["TLS_CERT_PATH"],
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
        table.add_column("Python time (s)", style="cyan")
        table.add_column("  of which Arrow serialization (s)", style="cyan")
        table.add_column("Server wait (s)", style="yellow")
        table.add_column("  write / finalize / rpc (s)", style="yellow")

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

            rosbag_size_mb = bag_path.stat().st_size / (1024 * 1024)
            console.print(
                f"[bold green]Starting ROS injestion {injestor_config.sequence_name} - Size (MB): {rosbag_size_mb:.2f} - bag number {loaded_bags + 1}/{len(filtered_rosbags)} [/bold green]"
            )

            injestor = RosbagInjector(injestor_config)

            try:
                with measure_upload() as timing:
                    injestor.run()

                # Filling statistics table
                with MosaicoClient.connect(
                    host=configs["MOSAICO_HOST"],
                    port=configs["MOSAICO_PORT"],
                    api_key=configs["API_KEY"],
                    enable_tls=configs["ENABLE_TLS"],
                    tls_cert_path=configs["TLS_CERT_PATH"],
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
                        f"{timing.total_s:.2f}",  # uploading time
                        f"{timing.python_s:.2f}",  # client-side Python time
                        f"{timing.serialize_s:.2f}",  # Python -> Arrow conversion
                        f"{timing.server_s:.2f}",  # time blocked on the server
                        f"{timing.write_s:.2f} / {timing.finalize_s:.2f} / {timing.rpc_s:.2f}",
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
                rosbag_path=Path(configs["PATH_TO_RECONSTRUCTED_BAGS"]),
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

            try:
                start = time.monotonic()
                extractor.run()
                elapsed_time = time.monotonic() - start

                # Filling statistics table

                with MosaicoClient.connect(
                    host=configs["MOSAICO_HOST"],
                    port=configs["MOSAICO_PORT"],
                    api_key=configs["API_KEY"],
                    enable_tls=configs["ENABLE_TLS"],
                    tls_cert_path=configs["TLS_CERT_PATH"],
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


START_STREAMING_TIMEOUT_S = 1.0  # in seconds


def kill_after_timeout(func):

    def wrapper(*args, **kwargs):

        def handler(signum, frame):
            raise TimeoutError(
                f"Function call exceded expeced timeout: {START_STREAMING_TIMEOUT_S}s"
            )

        old = signal.signal(signal.SIGALRM, handler)
        signal.setitimer(signal.ITIMER_REAL, START_STREAMING_TIMEOUT_S)

        try:
            return func(*args, **kwargs)

        finally:
            # Resetting previous SIGNAL handler
            signal.setitimer(signal.ITIMER_REAL, 0)  # always disarm the timer
            signal.signal(signal.SIGALRM, old)  # restore prior handler

    return wrapper


# @kill_after_timeout
def start_streaming(stremer: SequenceDataStreamer):
    for _, _ in stremer:
        return  # returns immediatelly as soon as first message arrives


def check_timestream_start(max_streasming_start_th_s: float):
    """
    This script executes a speedtest on how fast the streaming start for the loaded Mosaicos Sequences.
    The test expects some sequences to be present within the Mosaico server and only their streaming speed
    will be tested.

    Args:
        max_streasming_start_th_s (float): max time (in seconds) to wait for a stream to start. If the
            streaming requires more that this time the sequence streaming is interrupted.
    """

    START_STREAMING_TIMEOUT_S = max_streasming_start_th_s

    global_configs = load_global_config(BASE_DIR)

    with MosaicoClient.connect(
        host=global_configs["MOSAICO_HOST"],
        port=global_configs["MOSAICO_PORT"],
        api_key=global_configs["API_KEY"],
        enable_tls=global_configs["ENABLE_TLS"],
        tls_cert_path=global_configs["TLS_CERT_PATH"],
    ) as client:
        all_loaded_sequences = client.list_sequences()

        # Create table
        table = Table(title="Streaming Sequence Time Table")

        # Add columns
        table.add_column("Sequence name", style="magenta")
        table.add_column("Topic name", style="magenta")
        table.add_column("Ontology Tag", style="magenta")
        table.add_column("Sequence size", style="magenta")
        table.add_column("Chunk numbers", style="magenta")
        table.add_column("Streaming start time (s)", style="green")

        table.add_section()

        for seq_name in all_loaded_sequences:
            console.print(f"[bold]Considering loaded sequence {seq_name} [/bold]")

            s_handler = client.sequence_handler(seq_name)

            assert s_handler is not None

            # Streaming test on sequence handler
            sequence_stremer: SequenceDataStreamer = s_handler.get_data_streamer()

            try:
                start = time.monotonic()
                start_streaming(sequence_stremer)
                elapsed_time = time.monotonic() - start

            except TimeoutError:
                elapsed_time = START_STREAMING_TIMEOUT_S

            table.add_row(
                s_handler.name,  # Sequence name
                "-",  # Topic name (not available here)
                "-",  # Ontology tag (not available here)
                f"{(s_handler.total_size_bytes / 1024.0 / 1024.0 / 1024.0):0.2f}Gb",  # Sequence size
                "-",  # Chunk numbers (not available here)
                f"{elapsed_time:0.2f}"
                if elapsed_time < START_STREAMING_TIMEOUT_S
                else f"Greater than timeout {START_STREAMING_TIMEOUT_S}s: {elapsed_time}",  # Streaming start time
                style=None if elapsed_time < START_STREAMING_TIMEOUT_S else "on red",
            )

            sequence_stremer.close()

            # Streaming test on each topic handler
            for topic_name in s_handler.topics:
                t_handler = client.topic_handler(seq_name, topic_name)

                assert t_handler is not None

                # Streaming test on topic handler
                topic_stremer: SequenceDataStreamer = s_handler.get_data_streamer()

                try:
                    start = time.monotonic()
                    start_streaming(topic_stremer)
                    elapsed_time = time.monotonic() - start

                except TimeoutError:
                    elapsed_time = START_STREAMING_TIMEOUT_S

                table.add_row(
                    "-",  # Sequence name (not available here)
                    t_handler.name,  # Topic name (not available here)
                    t_handler.ontology_tag,  # Ontology tag
                    "-",  # Sequence size (not available here)
                    f"{t_handler.chunks_number}"
                    if t_handler.chunks_number
                    else "Unk",  # Chunk numbers
                    f"{elapsed_time:0.2f}"
                    if elapsed_time < START_STREAMING_TIMEOUT_S
                    else f"Greater than timeout {START_STREAMING_TIMEOUT_S}s",  # Streaming start time
                    style=None
                    if elapsed_time < START_STREAMING_TIMEOUT_S
                    else "on red",
                )

                topic_stremer.close()

        # printing resulting table
        console.print(table)
