# Mosaico Test Datasets

A collection of scripts that download publicly available ROS bag datasets and
inject them into a running [Mosaico](https://mosaico.dev) instance. The
primary use-case is validating that the Mosaico platform correctly ingests a
variety of real-world sensor recordings (LiDAR, cameras, GPS, IMU, …) from
different ROS distributions and robot platforms.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Running Mosaico Server](#running-mosaico-server)
- [Datasets](#datasets)
- [Global Configurations](#global-configurations)
- [Commands](#commands)
  - [1. Loading Datasets](#1-loading-datasets)
  - [2. Reconstructing Datasets](#2-reconstructing-datasets)
  - [3. Pruning Datasets](#3-pruning-datasets)
  - [4. Checking Streaming Start](#4-checking-streaming-start)
  - [5. Timing Statistics (upload + reconstruction)](#5-timing-statistics-upload--reconstruction)
- [Adding a New Dataset](#adding-a-new-dataset)

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | ≥ 3.13 |
| [Poetry](https://python-poetry.org/docs/#installation) | ≥ 2.0 |
| Docker + Docker Compose | any recent version |

---

## Installation

Install all Python dependencies with Poetry. No local Mosaico source checkout
is required — the `mosaicolabs` package is pulled from PyPI automatically.

```bash
# 1. Clone the repository
git clone <repo-url>
cd mosaico-test-datasets

# 2. Install dependencies (Poetry creates a .venv inside the project)
poetry install
```

> Note: Mosaico main repo should be available right next to `mosaico-test-datasets`

### Running Mosaico Server

All the next `commands` expect a live Mosaico server to be reachable. Create the Mosaico Server as you prefer and verify its presence with:

```bash
# Verify the daemon is listening on specified ip:port (in this case localhost:6276)
curl http://localhost:6726
```
---
## Datasets

### Global Configurations

The [configs.py](src/configs.py) file contains the global configurations shared among all the present [Datasets](src/Datasets/). Any key defined in a dataset-level `configs.py` overrides the corresponding global value (i.e. [src/Datasets/Agrikola/configs.py](src/Datasets/Agrikola/configs.py)).

> **Note** — Before ingesting a dataset make sure the rosbag files are present
> on disk at the path configured in the dataset's `configs.py`
> (see [`PATH_TO_BAGS`](#configuration-keys)). Each dataset folder that ships
> a download script can be used to fetch the bags automatically, e.g.:
>
> ```bash
> bash src/Datasets/UZH_FPV/download_uzh_fpv.sh
> bash src/Datasets/SugarBeets/download_ijrr_sugar_beet_2016_rosbag_data.sh
> ```

## Commands

### 1. Loading Datasets

The CLI entry-point is registered by Poetry as
`mosaicolabs.datasets.ingest_rosbags`. Run it through `poetry run`:

```bash
# Show all available options
poetry run mosaicolabs.datasets.ingest_rosbags --help

# Inject a single dataset
poetry run mosaicolabs.datasets.ingest_rosbags --datasets autoware
poetry run mosaicolabs.datasets.ingest_rosbags --datasets sugarbeets
poetry run mosaicolabs.datasets.ingest_rosbags --datasets uzh_fpv

# Inject multiple datasets in one go
poetry run mosaicolabs.datasets.ingest_rosbags --datasets autoware --datasets sugarbeets

# Inject all datasets
poetry run mosaicolabs.datasets.ingest_rosbags --all
```

Use `--n_bags` to limit how many bags are injected per dataset — useful
for smoke-testing without waiting for a full ingest:

```bash
poetry run mosaicolabs.datasets.ingest_rosbags --datasets autoware --n_bags 3
```

#### Configuration Keys

Every dataset is configured through a `configs.py` file. The following keys
are recognised:

| Key | Description | Default |
|---|---|---|
| `MOSAICO_HOST` | Hostname of the Mosaico daemon | `localhost` |
| `MOSAICO_PORT` | Port of the Mosaico daemon | `6726` |
| `PATH_TO_BAGS` | Absolute path to the directory containing the rosbags | `""` |
| `ROS_DISTRO` | `rosbags` store type (e.g. `Stores.ROS2_JAZZY`) | `None` |
| `TOPICS_TO_FILTER` | List of topic patterns to include/exclude (`!` prefix to exclude) | `None` (all topics) |
| `API_KEY` | Mosaico API key for authenticated instances | `None` |
| `ENABLE_TLS` | Whether to connect to the Mosaico daemon over TLS | `False` |
| `TLS_CERT_PATH` | Path to a TLS certificate for encrypted connections | `None` |

Global defaults live in `src/configs.py`. Any key defined in a
dataset-level `configs.py` overrides the corresponding global value.

---

### 2. Reconstructing Datasets

Previously ingested sequences can be pulled back out of Mosaico and rebuilt
as local rosbag files. This is useful to verify that data survives a
round-trip through the platform unchanged. The CLI entry-point
`mosaicolabs.datasets.reconstruct_rosbags` mirrors the loader interface:

```bash
# Show all available options
poetry run mosaicolabs.datasets.reconstruct_rosbags --help

# Reconstruct a single dataset
poetry run mosaicolabs.datasets.reconstruct_rosbags --datasets autoware
poetry run mosaicolabs.datasets.reconstruct_rosbags --datasets sugarbeets
poetry run mosaicolabs.datasets.reconstruct_rosbags --datasets uzh_fpv

# Reconstruct multiple datasets in one go
poetry run mosaicolabs.datasets.reconstruct_rosbags --datasets autoware --datasets sugarbeets

# Reconstruct all datasets
poetry run mosaicolabs.datasets.reconstruct_rosbags --all
```

Use `--n_sequences` to limit how many sequences are reconstructed per
dataset — useful for smoke-testing without waiting for a full round-trip:

```bash
poetry run mosaicolabs.datasets.reconstruct_rosbags --datasets autoware --n_sequences 3
```

For every rosbag found under the dataset's `PATH_TO_BAGS`, the command
derives the matching sequence name, downloads it from the Mosaico instance
configured in the dataset's `configs.py`, and writes it back out as a new
rosbag under `PATH_TO_RECONSTRUCTED_BAGS`, using the format selected via
`STORAGE_PLUGIN`. Existing files at the destination are overwritten.

#### Reconstruction-specific configuration keys

In addition to the [general configuration keys](#configuration-keys), the
following keys control the reconstruction behaviour:

| Key | Description | Default |
|---|---|---|
| `PATH_TO_RECONSTRUCTED_BAGS` | Directory where reconstructed rosbags are written | `"mnt/datasets/bags/reconstructed"` |
| `STORAGE_PLUGIN` | Rosbag2 storage format used for the reconstructed bags (`StoragePlugin.MCAP` or `StoragePlugin.SQLITE3`) | `StoragePlugin.MCAP` |
| `START_TIMESTAMP_NS` | Only reconstruct messages at or after this timestamp (nanoseconds) | `None` (from the start) |
| `END_TIMESTAMP_NS` | Only reconstruct messages at or before this timestamp (nanoseconds) | `None` (until the end) |

Global defaults live in `src/configs.py`. Any key defined in a
dataset-level `configs.py` overrides the corresponding global value.

---

### 3. Pruning Datasets

Sequences that have already been ingested can be removed from the Mosaico
server without touching the local rosbag files. The CLI entry-point
`mosaicolabs.datasets.delete_rosbags` mirrors the loader interface:

```bash
# Show all available options
poetry run mosaicolabs.datasets.delete_rosbags --help

# Prune a single dataset
poetry run mosaicolabs.datasets.delete_rosbags --datasets autoware
poetry run mosaicolabs.datasets.delete_rosbags --datasets sugarbeets
poetry run mosaicolabs.datasets.delete_rosbags --datasets uzh_fpv

# Prune multiple datasets in one go
poetry run mosaicolabs.datasets.delete_rosbags --datasets autoware --datasets sugarbeets

# Prune all datasets
poetry run mosaicolabs.datasets.delete_rosbags --all
```

Use `--n_bags` to limit how many sequences are pruned per dataset — useful
when you only want to free up a portion of the loaded data:

```bash
poetry run mosaicolabs.datasets.delete_rosbags --datasets autoware --n_bags 3
```

The command connects to the Mosaico instance configured in the dataset's
`configs.py`, lists all sequences currently loaded on the server, and deletes
only the ones whose names match rosbag files found under `PATH_TO_BAGS`.
Sequences that belong to other datasets are never touched.

---

### 4. Checking Streaming Start

Measures how long it takes for each sequence currently loaded on the Mosaico
server to start streaming — useful as a quick performance smoke test. It
requires sequences to already be loaded (see [Loading Datasets](#1-loading-datasets)).
The CLI entry-point is `mosaicolabs.datasets.check_start_streaming`:

```bash
# Show all available options
poetry run mosaicolabs.datasets.check_start_streaming --help

# Use a custom timeout (in seconds) before a stream is considered stuck
poetry run mosaicolabs.datasets.check_start_streaming --timeout 2.0
```

Unlike the other commands, this one is not scoped by `--datasets`/`--all`: it
connects using the global configuration in `src/configs.py` and reports on
every sequence currently loaded on the server, regardless of which dataset
originally loaded it.

---

### 5. Timing Statistics (upload + reconstruction)

[`scripts/launch_timing_statistics.sh`](scripts/launch_timing_statistics.sh)
launches a detached `tmux` session that runs ingestion followed by
reconstruction, one dataset at a time, for a configurable list of datasets.
Use it when you want to collect combined upload and rosbag reconstruction
timing statistics across datasets in a single unattended run. See the
comment block at the top of the script for the full usage details
(configuration variables, log file locations, how to attach/detach from the
session).

```bash
bash scripts/launch_timing_statistics.sh
```

---

## Adding a New Dataset

Follow these steps to register a new ROS bag dataset.

### 1. Create the dataset folder

Create a new sub-directory under `src/Datasets/` whose name will be used as
the dataset identifier. The folder **must** contain a `configs.py` file (even
if empty).

```
src/Datasets/
└── MyDataset/
    └── configs.py
```

### 2. Configure the dataset

Edit `src/Datasets/MyDataset/configs.py` and set at least `PATH_TO_BAGS` and
`ROS_DISTRO`. Take `src/Datasets/Autoware/configs.py` as a reference:

```python
from rosbags.typesys import Stores
from pathlib import Path

PATH_TO_BAGS = "mnt/datasets/bags/MyDataset"
ROS_DISTRO = Stores.ROS2_JAZZY  # or Stores.ROS1_NOETIC, etc.

# Optional: restrict which topics are injected.
# Prefix a pattern with '!' to exclude it.
TOPICS_TO_FILTER = [
    "/sensors/lidar/points",
    "/sensors/camera/*",
    "!/sensors/camera/raw",
]
```

Only the keys you define will override the global defaults; the rest inherit
from `src/configs.py`.

### 3. Register the dataset in the CLI

Open `src/cli.py` and add one entry to `AVAILABLE_DATASET_MAP` — the key
is the name passed to `--datasets` (lowercase, underscores), the value is the
exact folder name:

```python
AVAILABLE_DATASET_MAP = {
    "autoware": "Autoware",
    "sugarbeets": "SugarBeets",
    "uzh_fpv": "UZH_FPV",
    "mydataset": "MyDataset",  # <-- add this
}
```

That's all. The CLI picks up the new entry automatically via `click.Choice`.

### 4. (Optional) Add a download script

If the bags are publicly available, add a shell script to the dataset folder
so other contributors can fetch them easily:

```
src/Datasets/MyDataset/download_mydataset.sh
```

See `src/Datasets/UZH_FPV/download_uzh_fpv.sh` for an example that uses `wget`
with resume support and a success/failure summary.

### 5. Verify the setup

```bash
# Check the new dataset appears in --help (it should be listed under --datasets choices)
poetry run mosaicolabs.datasets.ingest_rosbags --help

# Smoke-test with a single bag
poetry run mosaicolabs.datasets.ingest_rosbags --datasets mydataset --n_bags 1
```
