from rosbags.typesys import Stores

PATH_TO_BAGS = "/mnt/datasets/bags/SugarBeets"
ROS_DISTRO = Stores.ROS1_NOETIC
TOPICS_TO_FILTER = [
    "/camera/*",
    "/gps/*",
    "!/gps/leica/time_reference",
    "/laser/fx8/points",
    "/odometry/*",
]
