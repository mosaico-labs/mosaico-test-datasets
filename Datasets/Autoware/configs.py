from rosbags.typesys import Stores

PATH_TO_BAGS = "/mnt/datasets/bags/Autoware"
ROS_DISTRO = Stores.ROS2_JAZZY
TOPICS_TO_FILTER = [
    "/applanix/*",
    "!/applanix/lvx_client/autoware_orientation",
    "/localization/twist_estimator/twist_with_covariance",
    "/pandar_points",
    "/tf_static",
]
