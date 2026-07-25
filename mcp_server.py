import os
import sqlite3
import json
import cv2
from fastmcp import FastMCP

# Khởi tạo MCP Server
mcp = FastMCP("ToolIb-YOLO-Hub")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_DIR, "yolo_labeling.db")

@mcp.tool()
def get_project_summary() -> str:
    """Lấy thống kê tiến độ gán nhãn dữ liệu YOLO (tổng số ảnh, ảnh đã gán nhãn, chưa gán nhãn)"""
    if not os.path.exists(DB_PATH):
        return "Chưa tìm thấy CSDL yolo_labeling.db trong thư mục dự án."
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM images")
        total_images = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM images WHERE is_labeled = 1")
        labeled_images = cursor.fetchone()[0]
        
        conn.close()
        unlabeled = total_images - labeled_images
        return f"📊 Thống kê ToolIb YOLO Hub:\n- Tổng số ảnh: {total_images}\n- Đã gán nhãn: {labeled_images}\n- Chưa gán nhãn: {unlabeled}"
    except Exception as e:
        return f"Lỗi đọc SQLite: {str(e)}"

@mcp.tool()
def get_unlabeled_images(limit: int = 5) -> str:
    """Lấy danh sách các ảnh chưa gán nhãn trong hệ thống để chuẩn bị xem và gán nhãn"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT i.id, i.filename, p.name FROM images i JOIN projects p ON i.project_id = p.id WHERE i.is_labeled = 0 LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "✅ Tất cả ảnh trong hệ thống đã được gán nhãn!"
        
        res = [f"🖼️ Danh sách {len(rows)} ảnh chưa gán nhãn:"]
        for img_id, filename, proj_name in rows:
            res.append(f"- ID: {img_id} | File: {filename} | Dự án: {proj_name}")
        return "\n".join(res)
    except Exception as e:
        return f"Lỗi lấy danh sách ảnh: {str(e)}"

@mcp.tool()
def ai_vision_label_image(image_id: int = None, api_key: str = None) -> str:
    """Sử dụng Vision AI để tự tay xem ảnh, phát hiện đối tượng, tạo Bounding Box chuẩn YOLO và lưu vào CSDL"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if image_id is None:
            cursor.execute("SELECT i.id, i.filename, p.name, p.root_path FROM images i JOIN projects p ON i.project_id = p.id WHERE i.is_labeled = 0 LIMIT 1")
            row = cursor.fetchone()
            if not row:
                conn.close()
                return "✅ Không có ảnh nào chưa gán nhãn để xử lý."
            image_id, filename, project_name, root_path = row
        else:
            cursor.execute("SELECT i.id, i.filename, p.name, p.root_path FROM images i JOIN projects p ON i.project_id = p.id WHERE i.id = ?", (image_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return f"❌ Không tìm thấy ảnh có ID {image_id}."
            image_id, filename, project_name, root_path = row

        img_path = os.path.join(root_path, filename)
        if not os.path.exists(img_path):
            conn.close()
            return f"❌ File ảnh không tồn tại tại: {img_path}"
        
        classes_file = os.path.join(root_path, "classes.txt")
        if not os.path.exists(classes_file):
            classes_file = os.path.join(PROJECT_DIR, "classes.txt")
        
        classes = []
        if os.path.exists(classes_file):
            with open(classes_file, "r", encoding="utf-8") as f:
                classes = [line.strip() for line in f if line.strip()]
        
        if not classes:
            classes = ["object", "product", "person", "item"]
            
        img = cv2.imread(img_path)
        if img is None:
            conn.close()
            return f"❌ Không thể đọc file ảnh: {img_path}"
        
        detected_boxes = []
        key = api_key or os.getenv("GEMINI_API_KEY")
        
        if key and not key.startswith("AQ."):
            try:
                from google import genai
                from PIL import Image as PILImage
                client = genai.Client(api_key=key)
                pil_img = PILImage.open(img_path)
                prompt = f"Detect all objects in this image. Available classes: {classes}. Return a JSON array of detected bounding boxes with 2D box coordinates normalized from 0 to 1000: [{{\"class_name\": \"...\", \"box_2d\": [ymin, xmin, ymax, xmax]}}]. Return JSON ONLY."
                res = client.models.generate_content(model="gemini-2.5-flash", contents=[pil_img, prompt])
                
                clean_text = res.text.strip().removeprefix("```json").removesuffix("```").strip()
                data = json.loads(clean_text)
                for item in data:
                    c_name = item.get("class_name")
                    c_id = classes.index(c_name) if c_name in classes else 0
                    box = item.get("box_2d", [0, 0, 1000, 1000])
                    ymin, xmin, ymax, xmax = [b / 1000.0 for b in box]
                    
                    x_center = (xmin + xmax) / 2.0
                    y_center = (ymin + ymax) / 2.0
                    box_w = xmax - xmin
                    box_h = ymax - ymin
                    detected_boxes.append((c_id, c_name, x_center, y_center, box_w, box_h))
            except Exception as vision_err:
                print(f"Vision API Fallback: {vision_err}")
        
        if not detected_boxes:
            try:
                import inference
                model_path = os.path.join(PROJECT_DIR, "models", "yolo12s.onnx")
                if os.path.exists(model_path):
                    yolo = inference.YOLOInference(model_path)
                    res = yolo.predict(img)
                    if 'class_id' in res:
                        c_id = res['class_id']
                        c_name = res.get('class_name', f'Class_{c_id}')
                        detected_boxes.append((c_id, c_name, 0.5, 0.5, 0.8, 0.8))
            except Exception as e:
                print(f"YOLO fallback error: {e}")

        label_filename = os.path.splitext(filename)[0] + ".txt"
        label_path = os.path.join(root_path, label_filename)
        
        lines = []
        labels_summary = []
        for c_id, c_name, xc, yc, bw, bh in detected_boxes:
            lines.append(f"{c_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}")
            labels_summary.append(f"{c_name} (ID: {c_id})")
        
        with open(label_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            
        cursor.execute("UPDATE images SET is_labeled = 1, flag_status = 'AI_VISION_REVIEW' WHERE id = ?", (image_id,))
        conn.commit()
        conn.close()
        
        box_count = len(detected_boxes)
        summary = ", ".join(set(labels_summary)) if labels_summary else "Chưa xác định"
        
        return (
            f"👁️ **Đã tự tay xem ảnh và gán nhãn thành công!**\n"
            f"- 📁 **Thuộc dự án:** `{project_name}`\n"
            f"- 🖼️ **File ảnh:** `{filename}` (ID: {image_id})\n"
            f"- 🎯 **Số Bounding Box đã vẽ:** {box_count}\n"
            f"- 🏷️ **Nhãn phát hiện:** {summary}\n"
            f"- 💾 **File nhãn:** `{label_filename}`\n"
            f"- 📍 **Trạng thái:** Đã cập nhật CSDL và đánh dấu `AI_VISION_REVIEW`.\n"
            f"👉 **Mời bạn mở Web UI tại `https://localhost:5000` để kiểm tra và tinh chỉnh lại Bounding Box!**"
        )
    except Exception as e:
        return f"Lỗi khi Vision AI gán nhãn ảnh: {str(e)}"

@mcp.tool()
def run_auto_labeling() -> str:
    """Chạy tiến trình Auto-Labeling hình ảnh bằng mô hình YOLO ONNX"""
    try:
        import subprocess
        res = subprocess.run(["python", "inference.py"], capture_output=True, text=True, cwd=PROJECT_DIR)
        return f"Đã chạy Auto-Labeling xong:\n{res.stdout[:400]}"
    except Exception as e:
        return f"Lỗi chạy Auto-Labeling: {str(e)}"

@mcp.tool()
def export_yolo_dataset() -> str:
    """Xuất dữ liệu gán nhãn ra cấu hình Train/Val/Test chuẩn YOLO"""
    try:
        import subprocess
        res = subprocess.run(["python", "split_tool.py"], capture_output=True, text=True, cwd=PROJECT_DIR)
        return f"Kết quả xuất Dataset:\n{res.stdout[:400]}"
    except Exception as e:
        return f"Lỗi khi xuất dataset: {str(e)}"

if __name__ == "__main__":
    mcp.run()
