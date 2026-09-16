from pathlib import Path
def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True,exist_ok=True)
    return path
def get_workspace_path(workspace:str|None =None)->Path:
    if workspace:
        path = Path(workspace).expanduser()
    else :
        path=Path.home()/".mybot"/"workspace"
    return ensure_dir(path)
def get_config_path()->Path :
    from mybot.config.loader import get_config_path as _loader_get_config_path
    return _loader_get_config_path()
