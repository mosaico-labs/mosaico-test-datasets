"""Offline: every dataset.toml loads, and a bad one is reported with its file name."""

import pytest

from src import ros_bridge


def test_every_ros_dataset_loads():
    assert ros_bridge.load_all()


@pytest.mark.parametrize(
    "toml, error",
    [
        (
            'bags = "x"\nros_distr = "ROS2_JAZZY"',
            "unexpected keyword argument 'ros_distr'",
        ),
        ('ros_distro = "ROS2_JAZZY"', "'bags'"),
        ('bags = "x"\nros_distro = "JAZZY"', "unknown value 'JAZZY'"),
        ('bags = "x"\nros_distro = ', "Invalid value"),
    ],
)
def test_bad_dataset_is_rejected(tmp_path, monkeypatch, toml, error):
    monkeypatch.setattr(ros_bridge, "BASE_DIR", tmp_path)
    (tmp_path / "dataset.toml").write_text(toml)
    with pytest.raises(ValueError, match="dataset.toml: ") as e:
        ros_bridge.load(tmp_path)
    assert error in str(e.value)


def test_relative_paths_resolve_against_the_dataset_folder(tmp_path):
    (tmp_path / "dataset.toml").write_text('bags = "bags"\nros_distro = "ROS1_NOETIC"')
    assert ros_bridge.load(tmp_path).bags == tmp_path / "bags"
