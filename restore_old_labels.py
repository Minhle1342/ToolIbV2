import os
import sys
import glob

def restore_yolo_labels(directory):
    """
    Scans a directory for YOLO .txt label files and restores the coordinates.
    The bad fix script added w/2 and h/2 to the centers incorrectly.
    This script reads those coordinates and subtracts them back to the original true center.
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
                cx_shifted = float(parts[1])
                cy_shifted = float(parts[2])
                w = float(parts[3])
                h = float(parts[4])
                
                # The bad script added abs(w) / 2 and abs(h) / 2
                # We simply subtract them back
                cx_true = cx_shifted - abs(w) / 2
                cy_true = cy_shifted - abs(h) / 2
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
            
    print(f"Restored {count} label files in {directory}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python restore_old_labels.py <directory_path>")
        print("Example: python restore_old_labels.py C:\\Users\\Minh\\Desktop\\dataset\\labels")
        sys.exit(1)
    
    target_dir = sys.argv[1]
    
    print(f"WARNING: This script will modify all .txt files in '{target_dir}'.")
    print("It assumes these files were incorrectly shifted by the fix_old_labels.py script.")
    print("This will SUBTRACT the offsets to return them to their original perfectly valid state.")
    confirm = input("Are you sure you want to proceed? (y/n): ")
    
    if confirm.lower() == 'y':
        restore_yolo_labels(target_dir)
    else:
        print("Operation cancelled.")
