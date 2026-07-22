import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox

def split_directory(src_dir, num_parts):
    # Lấy danh sách toàn bộ các file trong thư mục
    all_files = []
    for root, _, files in os.walk(src_dir):
        for file in files:
            full_path = os.path.join(root, file)
            # Lấy đường dẫn tương đối (giữ nguyên cấu trúc)
            rel_path = os.path.relpath(full_path, src_dir)
            all_files.append((full_path, rel_path))
    
    if not all_files:
        return False, "Thư mục trống, không có file nào để chia!"
    
    # Tạo thư mục chứa kết quả (nằm cạnh thư mục gốc)
    base_dir = os.path.dirname(src_dir)
    folder_name = os.path.basename(src_dir)
    output_root = os.path.join(base_dir, f"{folder_name}_split")
    os.makedirs(output_root, exist_ok=True)
    
    # Chia đều file cho các thư mục con theo vòng lặp (Round-Robin)
    for i, (full_path, rel_path) in enumerate(all_files):
        part_idx = (i % num_parts) + 1
        part_dir = os.path.join(output_root, f"Phan_{part_idx}")
        
        dest_path = os.path.join(part_dir, rel_path)
        
        # Tạo các thư mục con tương đương thư mục gốc
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # Copy file sang vị trí mới (thay shutil.copy2 bằng shutil.move nếu muốn cắt file)
        shutil.copy2(full_path, dest_path)
        
    return True, f"Thành công! Đã copy {len(all_files)} files thành {num_parts} thư mục tại:\n{output_root}"

# --- GIAO DIỆN NGƯỜI DÙNG (Tkinter) ---
def select_folder():
    folder_path = filedialog.askdirectory(title="Chọn thư mục")
    if folder_path:
        lbl_folder_path.config(text=folder_path)
        global selected_folder
        selected_folder = folder_path

def run_split():
    if not selected_folder:
        messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục cần chia!")
        return
    try:
        num = int(entry_num.get())
        if num < 2:
            messagebox.showwarning("Cảnh báo", "Số lượng thư mục con phải >= 2!")
            return
    except ValueError:
        messagebox.showerror("Lỗi", "Vui lòng nhập một số nguyên hợp lệ!")
        return
        
    btn_run.config(state=tk.DISABLED, text="Đang xử lý...")
    window.update()
    
    try:
        success, msg = split_directory(selected_folder, num)
        if success: messagebox.showinfo("Thành công", msg)
        else: messagebox.showwarning("Cảnh báo", msg)
    except Exception as e:
        messagebox.showerror("Lỗi", f"Có lỗi xảy ra:\n{str(e)}")
    finally:
        btn_run.config(state=tk.NORMAL, text="Bắt đầu chia")

selected_folder = ""
window = tk.Tk()
window.title("Công cụ chia nhỏ thư mục")
window.geometry("400x250")
window.eval('tk::PlaceWindow . center') # Căn giữa màn hình

tk.Label(window, text="1. Bấm để chọn thư mục gốc:", font=("Arial", 10, "bold")).pack(pady=10)
tk.Button(window, text="Upload / Chọn Thư Mục", command=select_folder).pack()
lbl_folder_path = tk.Label(window, text="(Chưa chọn thư mục nào)", fg="blue", wraplength=380)
lbl_folder_path.pack(pady=5)

tk.Label(window, text="2. Số lượng thư mục con muốn chia:", font=("Arial", 10, "bold")).pack(pady=10)
entry_num = tk.Entry(window, width=10, justify='center')
entry_num.insert(0, "2")
entry_num.pack()

btn_run = tk.Button(window, text="Bắt đầu chia", command=run_split, bg="green", fg="white", font=("Arial", 10, "bold"))
btn_run.pack(pady=20)

window.mainloop()
