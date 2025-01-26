from datetime import datetime
from pathlib import Path

cli_env: Path
data_path: Path
config_path: Path
log_path: Path
static_path: Path
cache_path: Path
maa_env: Path
maa_usrdir_path:Path

global_config: dict
personal_configs: list[dict]
config_templates: dict[dict]

tasks: list[dict]

verbose: bool
start_time: datetime
