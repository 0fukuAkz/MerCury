import pytest
import threading
import time
import os
import signal

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# Only import app dependencies if playwright is available
if HAS_PLAYWRIGHT:
    from mercury.web.app import create_app, init_db
    from mercury.data.database import get_session_direct
    from mercury.data.models import User
    from mercury.security.auth import hash_password

HOST = "127.0.0.1"
PORT = 5001
BASE_URL = f"http://{HOST}:{PORT}"

if HAS_PLAYWRIGHT:
    @pytest.fixture(scope="session")
    def flask_server():
        """Start Flask server in a separate thread."""
        # Use a file-based DB for E2E sharing between thread and main process
        db_path = "e2e_test.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
        os.environ["FLASK_ENV"] = "testing"
        
        app = create_app(config={
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f"sqlite:///{db_path}",
            'WTF_CSRF_ENABLED': False  # Disable CSRF for easier testing
        })
        
        # Initialize DB with admin user
        with app.app_context():
            init_db()
            session = get_session_direct()
            if not session.query(User).filter_by(username="admin").first():
                admin = User(
                    username="admin", 
                    email="admin@test.com",
                    is_admin=True,
                    is_active=True
                )
                admin.password_hash = hash_password("password")
                session.add(admin)
                session.commit()
            session.close()

        # Run server
        server_thread = threading.Thread(target=app.run, kwargs={'host': HOST, 'port': PORT, 'use_reloader': False})
        server_thread.daemon = True
        server_thread.start()
        
        # Wait for server to start
        time.sleep(2)
        
        yield BASE_URL
        
        # Cleanup
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except PermissionError:
                pass  # File might be locked on Windows

    @pytest.fixture(scope="session")
    def base_url(flask_server):
        return flask_server
