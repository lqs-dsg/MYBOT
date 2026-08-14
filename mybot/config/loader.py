import re
import json
import os
from pathlib import Path
from mybot.config.schema import Config


def _resolve_env_vars(value: str) -> str:
    pattern = re.compile(r"\$\{([^}]+)\}")

    def replace_match(match: re.Match) -> str:
        env_key = match.group(1)
        return os.environ.get(env_key, "")

    return pattern.sub(replace_match, value)


def _resolve_dict(obj):
    if isinstance(obj, dict):
        new_data = {}
        for k, v in obj.items():
            new_data[k] = _resolve_dict(v)
        return new_data
    elif isinstance(obj, list):
        new_list = []
        for item in obj:
            new_list.append(_resolve_dict(item))
        return new_list
    elif isinstance(obj, str):
        return _resolve_env_vars(obj)
    else:
        return obj

_current_config_path:Path|None=None
DEFAULT_CONFIG_PATH=Path.home()/".mybot"/"config.json"

def set_config_path(path:str|Path)->None:
    global _current_config_path
    _current_config_path =Path(path)
def get_config_path()->Path:
    if _current_config_path is not None:
        return _current_config_path
    return DEFAULT_CONFIG_PATH


def load_config(config_path: str | Path) -> Config:
    path =Path(config_path)
    global _current_config_path
    _current_config_path=path
    with open(path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        resolved_data = _resolve_dict(raw_data)
        config = Config.model_validate(resolved_data)
        return config
def save_config(config:Config,path:str|Path=None)->None:
    target_path=Path(path) if path else get_config_path()
    target_path.parent.mkdir(parents=True,exist_ok=True)
    dump_data =config.model_dump(by_alias=True)
    with open(target_path,"w",encoding="utf-8")  as f:
         json.dump(dump_data,f,ensure_ascii=False,indent=2)
    