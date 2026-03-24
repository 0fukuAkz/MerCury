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
        db_path = os.path.abspath("e2e_test.db")
        # Do NOT set global os.environ["DATABASE_URL"] here to avoid polluting other tests
        
        app_config = {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f"sqlite:///{db_path}",
            'WTF_CSRF_ENABLED': False,
            'SECRET_KEY': 'e2e-secret'
        }
        
        from mercury.web.app import create_app
        app = create_app(config=app_config)
        
        # Initialize DB with admin user using the specific app context
        with app.app_context():
            from mercury.data.database import init_db
            from sqlalchemy.orm import sessionmaker
            
            # Use init_db to create tables and return the engine
            engine = init_db(db_url=f"sqlite:///{db_path}")
            
            Session = sessionmaker(bind=engine)
            session = Session()
            
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
            
            user_count = session.query(User).count()
            print(f"DEBUG: E2E DB initialized. User count: {user_count}")
            session.close()
            engine.dispose()

        # Run server using a wrapper that ensures the right config is used
        def run_app():
            # Set the env var ONLY inside the thread if necessary, but app is already configured
            app.run(host=HOST, port=PORT, use_reloader=False, threaded=True)

        server_thread = threading.Thread(target=run_app)
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
