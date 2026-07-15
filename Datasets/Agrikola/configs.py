from rosbags.typesys import Stores
from pathlib import Path

PATH_TO_BAGS = Path.home() / "rosbags/Agrikola"
ROS_DISTRO = Stores.ROS2_JAZZY
TOPICS_TO_FILTER = ["*", "!/cam/*"]
