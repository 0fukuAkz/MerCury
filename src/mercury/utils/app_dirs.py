import sys
import os
from pathlib import Path
from platformdirs import user_data_dir, user_log_dir, user_config_dir

APP_NAME = "MerCury"
APP_AUTHOR = "MerCuryTeam"  # Needed for Windows paths

def is_frozen() -> bool:
    """Check if the application is running as a bundled executable."""
    return getattr(sys, 'frozen', False)

def get_data_dir() -> Path:
    """
    Get the application data directory.
    
    Returns:
        Path to local 'data' dir in dev mode, or system user data dir in frozen mode.
    """
    if is_frozen():
        path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    else:
        # Development mode: use local directory relative to project root
        # Assuming we are in src/mercury/utils/app_dirs.py -> ../../../
        path = Path(__file__).parent.parent.parent.parent / "data"
        
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_log_dir() -> Path:
    """
    Get the application log directory.
    
    Returns:
        Path to local 'logs' dir in dev mode, or system user log dir in frozen mode.
    """
    if is_frozen():
        path = Path(user_log_dir(APP_NAME, APP_AUTHOR))
    else:
        path = Path(__file__).parent.parent.parent.parent / "logs"
        
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_db_path() -> str:
    """
    Get the full path to the SQLite database.
    """
    # Allow override via env var for testing/docker
    if os.environ.get("DATABASE_URL"):
        return os.environ.get("DATABASE_URL")
        
    data_dir = get_data_dir()
    return f"sqlite:///{data_dir}/mercury.db"
