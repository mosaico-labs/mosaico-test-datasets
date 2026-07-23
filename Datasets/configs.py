# Global defaults — overridden per-dataset in each subfolder's configs.py
MOSAICO_HOST = "localhost"
MOSAICO_PORT = 6726
PATH_TO_BAGS = ""
ROS_DISTRO = None
TOPICS_TO_FILTER = None
API_KEY=None
ENABLE_TLS=False
TLS_CERT_PATH=None


# Global defaults — overridden per-dataset in each subfolder's configs.py
# Unloading parameters
STORAGE_PLUGIN = "MCAP" # possible: MCAP, SQLITE3
START_TIMESTAMP = None
STOP_TIMESTAMP = None