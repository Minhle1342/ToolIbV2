import sqlite3
import os

def update_database():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yolo_labeling.db')
    
    if not os.path.exists(db_path):
        print(f"[ERROR] Database not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    migrations = [
        ("ai_models", "model_type", "ALTER TABLE ai_models ADD COLUMN model_type VARCHAR(50) DEFAULT 'detection'"),
        ("images", "is_reviewed", "ALTER TABLE images ADD COLUMN is_reviewed BOOLEAN DEFAULT 0"),
    ]

    for table, column, sql in migrations:
        try:
            cursor.execute(sql)
            conn.commit()
            print(f"  [OK] Added column '{column}' to table '{table}'.")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"  [SKIP] Column '{column}' already exists in '{table}'.")
            else:
                print(f"  [WARN] {e}")

    conn.close()
    print("\nDatabase update complete!")

if __name__ == '__main__':
    print("Updating database schema...\n")
    update_database()
