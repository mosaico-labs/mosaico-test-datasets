from rosbags.rosbag2 import StoragePlugin

# Global defaults — overridden per-dataset in each subfolder's configs.py
MOSAICO_HOST = "localhost"
MOSAICO_PORT = 6726
PATH_TO_BAGS = ""
ROS_DISTRO = None
TOPICS_TO_FILTER = None
API_KEY = None
ENABLE_TLS = False
TLS_CERT_PATH = None


# Global defaults — overridden per-dataset in each subfolder's configs.py
# Unloading parameters
PATH_TO_RECONSTRUCTED_BAGS = "/mnt/datasets/bags/reconstructed"
STORAGE_PLUGIN = StoragePlugin.MCAP  # possible: MCAP, SQLITE3
START_TIMESTAMP_NS = None
END_TIMESTAMP_NS = None
