import signal
import sys
import time

import click
from mosaicolabs import MosaicoClient, SequenceDataStreamer
from mosaicolabs_cli.utils.mosaico_profile import MosaicoProfile
from rich.console import Console
from rich.table import Table

from . import ros_bridge
from .ros_bridge import (
    load_datasets,
    prune_datasets,
    unload_datasets,
)

AVAILABLE_DATASET_MAP = {
    "autoware": "Autoware",
    "sugarbeets": "SugarBeets",
    "uzh_fpv": "UZH_FPV",
    "agrikola": "Agrikola",
    # "niulinx": "Niulinx",
    "nvidia": "Nvidia",
    "unipi": "Unipi",
}

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--datasets",
    "datasets",
    multiple=True,
    type=click.Choice(list(AVAILABLE_DATASET_MAP.keys()), case_sensitive=False),
    help="Dataset to load. Can be repeated to select multiple datasets.",
)
@click.option("--all", is_flag=True, help="Considers all defined datasets.")
@click.option(
    "--n_bags",
    default=None,
    type=int,
    help="Number of bags to load per dataset. Omit to load all available bags.",
)
def run_dataset_injestor(datasets, all, n_bags):
    """
    Mosaico dataset loader Runner

    This utility allows you to start rosbags dataset injestion
    """
    if all:
        datasets = list(AVAILABLE_DATASET_MAP.values())
    else:
        datasets = [AVAILABLE_DATASET_MAP[d] for d in datasets]

    if not datasets:
        click.secho(
            "No datasets to injest requested. Please run the command with --help to see all available  Datasets",
            fg="cyan",
            bold=True,
        )
        sys.exit(0)

    click.secho(f"Requested injestion of {datasets} dataset(s)", fg="cyan", bold=True)

    try:
        load_datasets(datasets, n_bags)

    except Exception as e:
        click.secho(f"\nExecution failed: {e}", fg="red", bold=True)
        sys.exit(1)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--datasets",
    "datasets",
    multiple=True,
    type=click.Choice(list(AVAILABLE_DATASET_MAP.keys()), case_sensitive=False),
    help="Dataset to delete. Can be repeated to select multiple datasets.",
)
@click.option("--all", is_flag=True, help="Considers all defined datasets.")
@click.option(
    "--n_bags",
    default=None,
    type=int,
    help="Number of bags to delete per dataset. Omit to delete all available bags.",
)
def run_dataset_eraser(datasets, all, n_bags):
    """
    Mosaico dataset Pruning Runner

    This utility allows you to start rosbags dataset injestion
    """
    if all:
        datasets = list(AVAILABLE_DATASET_MAP.values())
    else:
        datasets = [AVAILABLE_DATASET_MAP[d] for d in datasets]

    if not datasets:
        click.secho(
            "No datasets to injest requested. Please run the command with --help to see all available  Datasets",
            fg="cyan",
            bold=True,
        )
        sys.exit(0)

    click.secho(f"Requested pruning of {datasets} dataset(s)", fg="cyan", bold=True)

    try:
        prune_datasets(datasets, n_bags)

    except Exception as e:
        click.secho(f"\nExecution failed: {e}", fg="red", bold=True)
        sys.exit(1)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--datasets",
    "datasets",
    multiple=True,
    type=click.Choice(list(AVAILABLE_DATASET_MAP.keys()), case_sensitive=False),
    help="Dataset to delete. Can be repeated to select multiple datasets.",
)
@click.option("--all", is_flag=True, help="Considers all defined datasets.")
@click.option(
    "--n_sequences",
    default=None,
    type=int,
    help="Number of bags to delete per dataset. Omit to delete all available bags.",
)
def run_unload_datasets(datasets, all, n_sequences):
    """
    Mosaico dataset Pruning Runner

    This utility allows you to start rosbags dataset injestion
    """
    if all:
        datasets = list(AVAILABLE_DATASET_MAP.values())
    else:
        datasets = [AVAILABLE_DATASET_MAP[d] for d in datasets]

    if not datasets:
        click.secho(
            "No datasets to injest requested. Please run the command with --help to see all available  Datasets",
            fg="cyan",
            bold=True,
        )
        sys.exit(0)

    click.secho(f"Requested pruning of {datasets} dataset(s)", fg="cyan", bold=True)

    try:
        unload_datasets(datasets, n_sequences)

    except Exception as e:
        click.secho(f"\nExecution failed: {e}", fg="red", bold=True)
        sys.exit(1)


console = Console()


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

    profile = MosaicoProfile.resolve()

    with MosaicoClient.connect(
        host=profile.host,
        port=profile.port,
        api_key=profile.api_key,
        enable_tls=profile.enable_tls,
        tls_cert_path=profile.tls_cert_path,
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


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--timeout",
    default=1.0,
    type=float,
    help="Timeout before streaming is aborted.",
)
def run_check_timestream_start(timeout):
    """
    Mosaico dataset checking start streaming time. It requires some sequences to be loaded in the server

    This utility allows you to start checking each sequence streaming time
    """

    try:
        check_timestream_start(timeout)

    except Exception as e:
        click.secho(f"\nExecution failed: {e}", fg="red", bold=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# mosaico-datasets: `<verb> <bridge>`, same order as the `mosaico` CLI
# ---------------------------------------------------------------------------

BRIDGES = {"ros": ros_bridge}


@click.group(context_settings=CONTEXT_SETTINGS)
def main():
    """Inject, extract and delete test datasets on a Mosaico server.

    The connection comes from your default Mosaico profile
    (see `mosaico profile ls`) or the MOSAICO_* environment variables.
    """


for verb in ("inject", "extract", "delete"):
    group = click.Group(verb, help=f"{verb.capitalize()} datasets. Pick a bridge.")
    for name, bridge in BRIDGES.items():
        group.add_command(getattr(bridge, verb), name)
    main.add_command(group)

main.add_command(run_check_timestream_start, "check-start-streaming")
