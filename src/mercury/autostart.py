import sys
import threading
import os

# Ensure we can find the mercury package if running from source (not frozen)
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import webview
from mercury.web.app import create_app, socketio
from mercury.utils.app_dirs import get_log_dir
from mercury.utils.logging_config import configure_logging

def run_server(app, host, port):
    """Run Flask/SocketIO server in background thread."""
    if socketio:
        socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=False, use_reloader=False)

def main():
    """Main entry point for frozen application."""
    port = 8080
    host = '127.0.0.1'
    url = f'http://{host}:{port}'
    
    # Configure Logging
    log_file = get_log_dir() / "mercury.app.log"
    configure_logging(level="INFO", log_file=str(log_file))
    
    # Create Flask App
    app = create_app()
    
    # Start Flask server in background thread
    server_thread = threading.Thread(target=run_server, args=(app, host, port), daemon=True)
    server_thread.start()
    
    # Create native window (main thread)
    window = webview.create_window(
        title='MerCury',
        url=url,
        width=1280,
        height=800,
        resizable=True,
        min_size=(800, 600)
    )
    # Enable downloads and configure webview settings
    webview.start(
        private_mode=False,  # Allow cookies/storage
        storage_path=str(get_log_dir().parent),  # Store in app data dir
    )

if __name__ == '__main__':
    # Fix multiprocessing on Windows (PyInstaller)
    import multiprocessing
    multiprocessing.freeze_support()
    
    main()
