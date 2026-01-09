
import sqlite3
import os

# Define database path (dev mode)
DB_PATH = "data/mercury.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}, skipping migration (will be created by app).")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get existing columns
    cursor.execute("PRAGMA table_info(global_settings)")
    columns = [info[1] for info in cursor.fetchall()]
    
    updates = [
        ("batch_size", "INTEGER DEFAULT 1000"),
        ("default_sender_name", "VARCHAR(255)"),
        ("default_test_email", "VARCHAR(255)"),
        ("log_retention_days", "INTEGER DEFAULT 30"),
        ("log_level", "VARCHAR(20) DEFAULT 'INFO'"),
        ("ui_theme", "VARCHAR(20) DEFAULT 'dark'")
    ]
    
    print("Checking for missing columns...")
    for col_name, col_def in updates:
        if col_name not in columns:
            print(f"Adding column: {col_name}")
            try:
                cursor.execute(f"ALTER TABLE global_settings ADD COLUMN {col_name} {col_def}")
            except Exception as e:
                print(f"Error adding {col_name}: {e}")
        else:
            print(f"Column {col_name} already exists.")
            
    conn.commit()
    conn.close()
    print("Migration check complete.")

if __name__ == "__main__":
    migrate()
