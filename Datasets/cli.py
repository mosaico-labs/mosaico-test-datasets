from .scripts import load_datasets, prune_datasets

import click
import sys

AVAILABLE_DATASET_MAP = {
    "autoware": "Autoware",
    "sugarbeets": "SugarBeets",
    "uzh_fpv": "UZH_FPV",
    "agrikola": "Agrikola",
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

    click.secho(
        f"Requested injestion of {datasets} dataset(s)", fg="cyan", bold=True
    )

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

    click.secho(
        f"Requested pruning of {datasets} dataset(s)", fg="cyan", bold=True
    )

    try:
        prune_datasets(datasets, n_bags)

    except Exception as e:
        click.secho(f"\nExecution failed: {e}", fg="red", bold=True)
        sys.exit(1)
