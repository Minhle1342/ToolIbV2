import os
import sys
import glob

def fix_yolo_labels(directory):
    """
    Scans a directory for YOLO .txt label files and corrects the coordinates.
    The previous bug incorrectly saved the top-left corner as the center (cx, cy).
    This script reads those coordinates and shifts them to the true center.
    """
    if not os.path.isdir(directory):
        print(f"Error: Directory '{directory}' does not exist.")
        return

    txt_files = glob.glob(os.path.join(directory, '*.txt'))
    count = 0
    for file_path in txt_files:
        if os.path.basename(file_path) == 'classes.txt':
            continue
            
        with open(file_path, 'r') as f:
            lines = f.readlines()
            
        new_lines = []
        modified = False
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 5:
                class_id = parts[0]
                cx_top_left = float(parts[1])
                cy_top_left = float(parts[2])
                w = float(parts[3])
                h = float(parts[4])
                
                # The bug saved top-left as cx, cy and possibly negative w, h
                cx_true = cx_top_left + abs(w) / 2
                cy_true = cy_top_left + abs(h) / 2
                w_true = abs(w)
                h_true = abs(h)
                
                # Prevent shifting out of bounds (0-1 range for YOLO)
                cx_true = max(0.0, min(1.0, cx_true))
                cy_true = max(0.0, min(1.0, cy_true))
                
                new_line = f"{class_id} {cx_true:.6f} {cy_true:.6f} {w_true:.6f} {h_true:.6f}\n"
                new_lines.append(new_line)
                modified = True
            else:
                new_lines.append(line)
                
        if modified:
            with open(file_path, 'w') as f:
                f.writelines(new_lines)
            count += 1
            
    print(f"Fixed {count} label files in {directory}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python fix_old_labels.py <directory_path>")
        print("Example: python fix_old_labels.py C:\\Users\\Minh\\Desktop\\dataset\\labels")
        sys.exit(1)
    
    target_dir = sys.argv[1]
    
    # Require explicit confirmation so users don't run it twice accidentally
    print(f"WARNING: This script will modify all .txt files in '{target_dir}'.")
    print("It assumes these files were generated WITH THE BUG (where top-left was saved instead of center).")
    print("DO NOT run this script on already correct labels or run it twice, as it will shift them again!")
    confirm = input("Are you sure you want to proceed? (y/n): ")
    
    if confirm.lower() == 'y':
        fix_yolo_labels(target_dir)
    else:
        print("Operation cancelled.")
