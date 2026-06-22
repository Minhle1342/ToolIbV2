import sqlite3
import os

def update_database():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yolo_labeling.db')
    
    if not os.path.exists(db_path):
        print(f"❌ Không tìm thấy file database tại: {db_path}")
        return

    try:
        # Kết nối trực tiếp vào file database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Thêm cột model_type với giá trị mặc định là 'detection' cho các model cũ
        cursor.execute("ALTER TABLE ai_models ADD COLUMN model_type VARCHAR(50) DEFAULT 'detection'")
        conn.commit()
        
        print("✅ Đã cập nhật Database thành công! Đã thêm cột 'model_type' vào bảng 'ai_models'.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower() or "exists" in str(e).lower():
             print("✅ Cột 'model_type' đã tồn tại trong database. Không cần cập nhật thêm.")
        else:
             print(f"⚠️ Thông báo SQLite: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    print("Đang kiểm tra và cập nhật database...")
    update_database()
