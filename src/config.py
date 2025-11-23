import yaml
import os
from typing import Dict, Any

CONFIG_FILE = "config.yaml"

DEFAULT_CONFIG = {
    "mount_point_template": "/media/sd-backup-{uuid}",
    "target_path_template": "~/backups/{date}",
    "graphql_host": "127.0.0.1",
    "graphql_port": 0,
    "log_path": None,
}

def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    
    with open(CONFIG_FILE, "r") as f:
        try:
            return yaml.safe_load(f) or DEFAULT_CONFIG
        except yaml.YAMLError:
            return DEFAULT_CONFIG

def save_config(config: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f)

def update_config(key: str, value: Any) -> None:
    config = load_config()
    # Simple key update for now, can be expanded for nested keys if needed
    config[key] = value
    save_config(config)
