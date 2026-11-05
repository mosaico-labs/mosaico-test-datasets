from rosbags.rosbag2 import StoragePlugin

# Global defaults — overridden per-dataset in each subfolder's configs.py
PATH_TO_BAGS = ""
ROS_DISTRO = None
TOPICS_TO_FILTER = None


# Global defaults — overridden per-dataset in each subfolder's configs.py
# Unloading parameters
PATH_TO_RECONSTRUCTED_BAGS = "/mnt/datasets/bags/reconstructed"
STORAGE_PLUGIN = StoragePlugin.MCAP  # possible: MCAP, SQLITE3
START_TIMESTAMP_NS = None
END_TIMESTAMP_NS = None
