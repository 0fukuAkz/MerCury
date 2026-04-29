#!/usr/bin/env python3
"""
Launcher script for MerCury.
Automatically manages virtual environment and dependencies.
Includes graceful shutdown and Windows process cleanup.
"""

import argparse
import os
import sys
import subprocess
import venv
import signal
import atexit
import threading
from pathlib import Path

# Constants
ROOT_DIR = Path(__file__).parent.absolute()
VENV_DIR = ROOT_DIR / "venv"
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
PID_FILE = ROOT_DIR / "data" / ".mercury.pid"

# Global for cleanup
_app = None
_gunicorn_proc = None
_shutdown_event = threading.Event()


def is_venv():
    """Check if running inside a virtual environment."""
    return (hasattr(sys, 'real_prefix') or
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))


def get_venv_python():
    """Get path to virtual environment python executable."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def create_venv():
    """Create virtual environment."""
    print(f"Creating virtual environment in {VENV_DIR}...")
    venv.create(VENV_DIR, with_pip=True)


def install_dependencies(python_path):
    """Install dependencies using the venv python."""
    print("Installing dependencies...")
    try:
        subprocess.check_call([str(python_path), "-m", "pip", "install", "--upgrade", "pip"])
        
        if REQUIREMENTS_FILE.exists():
            subprocess.check_call([str(python_path), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])
            subprocess.check_call([str(python_path), "-m", "pip", "install", "-e", ".", "--no-deps"])
        else:
            print("Warning: requirements.txt not found!")
            
    except subprocess.CalledProcessError as e:
        print(f"Error installing dependencies: {e}")
        sys.exit(1)


def write_pid():
    """Write current process ID to file for cleanup."""
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def remove_pid():
    """Remove PID file on exit."""
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


def kill_existing_instances():
    """Kill any existing MerCury instances (Windows shadow process cleanup)."""
    if sys.platform != "win32":
        return
    
    try:
        # Check for existing PID file
        if PID_FILE.exists():
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            
            # Try to kill old process
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_TERMINATE = 1
                handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, old_pid)
                if handle:
                    kernel32.TerminateProcess(handle, 0)
                    kernel32.CloseHandle(handle)
                    print(f"Cleaned up previous instance (PID: {old_pid})")
            except Exception:
                pass
        
        # Also kill any python processes using port 5000
        try:
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.split('\n'):
                if ':5000' in line and 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = int(parts[-1])
                        if pid != os.getpid():
                            try:
                                subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                             capture_output=True, timeout=5)
                                print(f"Killed shadow process on port 5000 (PID: {pid})")
                            except Exception:
                                pass
        except Exception:
            pass
            
    except Exception:
        pass


def graceful_shutdown(signum=None, frame=None):
    """Handle graceful shutdown on Ctrl+C or termination."""
    print("\n" + "="*50)
    print("🛑 Shutting down MerCury gracefully...")
    print("="*50)
    
    _shutdown_event.set()
    
    # Stop Gunicorn if running
    global _gunicorn_proc
    if _gunicorn_proc:
        try:
            _gunicorn_proc.terminate()
            _gunicorn_proc.wait(timeout=10)
            print("✓ Gunicorn stopped")
        except Exception:
            pass
    
    # Clean up PID file
    remove_pid()
    print("✓ Cleanup complete")
    
    # On Windows, forcefully clean up any lingering processes
    if sys.platform == "win32":
        try:
            # Kill any child processes
            import ctypes
            current_pid = os.getpid()
            subprocess.run(
                f'wmic process where (ParentProcessId={current_pid}) delete',
                shell=True,
                capture_output=True,
                timeout=5
            )
        except Exception:
            pass
    
    print("👋 MerCury stopped. Goodbye!")
    sys.exit(0)


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown."""
    # Handle Ctrl+C
    signal.signal(signal.SIGINT, graceful_shutdown)
    
    # Handle termination request
    signal.signal(signal.SIGTERM, graceful_shutdown)
    
    # Windows-specific: Handle console close
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            
            # Set console control handler
            CTRL_C_EVENT = 0
            CTRL_BREAK_EVENT = 1
            CTRL_CLOSE_EVENT = 2
            
            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
            def console_handler(event):
                if event in (CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT):
                    graceful_shutdown()
                    return True
                return False
            
            kernel32.SetConsoleCtrlHandler(console_handler, True)
        except Exception:
            pass
    
    # Register cleanup on exit
    atexit.register(remove_pid)


def main():
    """Main entry point."""

    parser = argparse.ArgumentParser(
        description='MerCury Email Platform',
        add_help=True,
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        default=False,
        help='Enable debug mode (verbose logging, auto-reload)',
    )
    args, _unknown = parser.parse_known_args()

    # --debug flag takes priority over the environment variable
    if args.debug:
        os.environ['FLASK_DEBUG'] = '1'

    # Check if we need to switch to venv
    if not is_venv():
        if not VENV_DIR.exists():
            create_venv()
            install_dependencies(get_venv_python())
        
        venv_python = get_venv_python()
        if not venv_python.exists():
            print(f"Error: Virtual environment python not found at {venv_python}")
            print("Please delete the 'venv' folder and try again.")
            sys.exit(1)

        print(f"Re-launching in virtual environment...")
        try:
            sys.exit(subprocess.call([str(venv_python), __file__] + sys.argv[1:]))
        except KeyboardInterrupt:
            sys.exit(0)

    # --- Running inside Venv ---
    
    # Set up signal handlers first
    setup_signal_handlers()
    
    # Kill any existing shadow instances (Windows)
    kill_existing_instances()
    
    # Write PID file
    write_pid()
    
    # Add src to path
    src_dir = ROOT_DIR / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    print(f"""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   🚀 MerCury Email Platform                              ║
║   Press Ctrl+C to stop gracefully                        ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")
    print(f"Python: {sys.executable}")
    print(f"PID: {os.getpid()}")
    print()
    
    try:
        import shutil
        gunicorn_path = shutil.which("gunicorn") or str(Path(sys.executable).parent / "gunicorn")

        is_debug = os.environ.get('FLASK_DEBUG', '0').lower() in ('true', '1')

        # In debug mode: all output to stdout, full access log
        # In normal mode: access log goes to file only, warnings+ to stdout
        if is_debug:
            log_args = [
                "--log-level", "debug",
                "--access-logfile", "-",
            ]
        else:
            log_dir = ROOT_DIR / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_args = [
                "--log-level", "warning",
                "--access-logfile", str(log_dir / "access.log"),
                "--error-logfile", "-",
            ]

        cmd = [
            gunicorn_path,
            "--worker-class", "eventlet",
            "-w", "1",
            "--bind", "0.0.0.0:5000",
            *log_args,
            "mercury.web.app:create_app()",
        ]

        env = {**os.environ, "PYTHONPATH": str(ROOT_DIR / "src")}

        global _gunicorn_proc
        _gunicorn_proc = subprocess.Popen(cmd, env=env)
        _gunicorn_proc.wait()

    except FileNotFoundError:
        print("\nError: gunicorn not found. Run: pip install gunicorn eventlet")
        sys.exit(1)
    except ImportError as e:
        print(f"\nError importing application: {e}")
        print("Dependencies might be missing. Try deleting 'venv' folder and re-running.")
        sys.exit(1)
    except KeyboardInterrupt:
        graceful_shutdown()
    except Exception as e:
        print(f"\nRuntime Error: {e}")
        sys.exit(1)
    finally:
        remove_pid()


if __name__ == "__main__":
    main()

