from typing import Optional, Dict, Any, Union
from confz import BaseConfig, FileSource
import yaml
import os

CONFIG_FILE = "config.yaml"

class AppConfig(BaseConfig):
    mount_point_template: str = "/media/sd-backup-{uuid}"
    target_path_template: str = "~/backups/{date}"
    graphql_host: str = "127.0.0.1"
    graphql_port: int = 0
    log_path: Optional[str] = None

    CONFIG_SOURCES = FileSource(file=CONFIG_FILE)

def update_config(key_or_dict: Union[str, Dict[str, Any]], value: Any = None) -> None:
    """
    Update configuration.
    Supports scalar update: update_config("key", value)
    Supports vector update: update_config({"key": value, "key2": value2})
    """
    current_config = AppConfig().dict()
    
    if isinstance(key_or_dict, dict):
        current_config.update(key_or_dict)
    else:
        current_config[key_or_dict] = value
        
    # Save back to file
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(current_config, f)
