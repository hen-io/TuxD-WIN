DOMAIN = "tuxd"
WS_PATH = "/api/tuxd/ws"

IMAGES_URL_PREFIX = "/api/tuxd/images"
ENTITY_PICTURE_LOGO = f"{IMAGES_URL_PREFIX}/logo.png"

HUB_IDENTIFIER = "hub"

CONF_PAIRING_KEY = "pairing_key"

ISSUE_PENDING_DEVICES = "pending_devices"

SIGNAL_NEW_ENTITY = "tuxd_new_entity_{domain}"
SIGNAL_REMOVE_ENTITY = "tuxd_remove_entity_{domain}"
SIGNAL_STATE_UPDATE = "tuxd_state_{unique_id}"
SIGNAL_HUB_STATS_UPDATE = "tuxd_hub_stats_update"
SIGNAL_LAST_SEEN_UPDATE = "tuxd_last_seen_{device_id}"
SIGNAL_DEVICE_APPROVED = "tuxd_device_approved"
SIGNAL_OFFLINE_UPDATE_URL_CHANGED = "tuxd_offline_update_url_changed"
SIGNAL_THRESHOLDS_CHANGED = "tuxd_thresholds_changed"
SIGNAL_ONLINE_TIMEOUT_CHANGED = "tuxd_online_timeout_changed"
SIGNAL_LAST_SEEN_ENABLED_CHANGED = "tuxd_last_seen_enabled_changed"
SIGNAL_ONLINE_SENSORS_ENABLED_CHANGED = "tuxd_online_sensors_enabled_changed"
ONLINE_TIMEOUT_DEFAULT = 300
LAST_SEEN_UPDATE_INTERVAL_DEFAULT = 300
SIGNAL_LAST_SEEN_UPDATE_INTERVAL_CHANGED = "tuxd_last_seen_update_interval_changed"

THRESHOLD_METRICS = [
    ("cpu_load", "CPU Load", "mdi:cpu-64-bit", "%", 0, 100, 1, 90),
    ("memory_used_percent", "RAM Use", "mdi:memory", "%", 0, 100, 1, 90),
    ("network_in_out", "Network RX+TX", "mdi:lan", "Mbit/s", 0, 100000, 1, 100),
    ("iowait_pct", "IO Wait", "mdi:timer-sand", "%", 0, 100, 1, 20),
    ("storage_used_pct", "Root Storage Used", "mdi:harddisk", "%", 0, 100, 1, 90),
    ("load_avg_1m", "Load Average 1m", "mdi:gauge", None, 0, 1000, 0.1, 4),
    ("load_avg_5m", "Load Average 5m", "mdi:gauge", None, 0, 1000, 0.1, 4),
    ("load_avg_15m", "Load Average 15m", "mdi:gauge", None, 0, 1000, 0.1, 4),
]

PLATFORMS = [
    "sensor",
    "binary_sensor",
    "number",
    "switch",
    "text",
    "button",
    "update",
    "select",
]
