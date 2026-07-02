#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
YOLO Bounding Box NMS Clean-up Tool
------------------------------------
Author: Antigravity AI
Description: This script reads YOLO-format text files, detects overlapping bounding boxes
             using IoU (Intersection over Union), and removes duplicate/overlapping boxes
             above a user-defined threshold, leaving only one bounding box per area.
             Supports class-specific NMS, confidence scores (if present), and area sorting.
"""

import os
import sys
import argparse
from typing import List, Dict, Any

def yolo_to_corners(x_center: float, y_center: float, width: float, height: float) -> List[float]:
    """Convert YOLO format (x_center, y_center, width, height) to corners (x_min, y_min, x_max, y_max)."""
    x_min = x_center - width / 2.0
    y_min = y_center - height / 2.0
    x_max = x_center + width / 2.0
    y_max = y_center + height / 2.0
    return [x_min, y_min, x_max, y_max]

def calculate_iou(box1: List[float], box2: List[float]) -> float:
    """Calculate the Intersection over Union (IoU) of two bounding boxes in corner format."""
    x_min_inter = max(box1[0], box2[0])
    y_min_inter = max(box1[1], box2[1])
    x_max_inter = min(box1[2], box2[2])
    y_max_inter = min(box1[3], box2[3])

    # Check if there is an intersection
    if x_max_inter < x_min_inter or y_max_inter < y_min_inter:
        return 0.0

    inter_area = (x_max_inter - x_min_inter) * (y_max_inter - y_min_inter)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union_area = box1_area + box2_area - inter_area

    if union_area == 0.0:
        return 0.0

    return inter_area / union_area

def clean_yolo_boxes(
    lines: List[str], 
    iou_threshold: float, 
    class_agnostic: bool = False,
    priority_metric: str = "area"
) -> List[str]:
    """
    Applies Non-Maximum Suppression to YOLO bounding boxes.
    
    Args:
        lines: List of raw lines from a YOLO format text file.
        iou_threshold: IoU overlap threshold above which boxes are deduplicated.
        class_agnostic: If True, suppress overlapping boxes even if they belong to different classes.
        priority_metric: If no confidence is present, sort boxes by "area" (descending) or "original" order.
    """
    parsed_boxes = []
    
    for idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) < 5:
            # Skip invalid lines
            continue
            
        try:
            class_id = int(parts[0])
            x_center = float(parts[1])
            y_center = float(parts[2])
            width = float(parts[3])
            height = float(parts[4])
            
            # Check if there's a 6th value for confidence score (e.g. from prediction outputs)
            confidence = float(parts[5]) if len(parts) >= 6 else 1.0
            
            # Corner coords for IoU calculation
            corners = yolo_to_corners(x_center, y_center, width, height)
            area = width * height
            
            parsed_boxes.append({
                'class_id': class_id,
                'box': corners,
                'yolo_coords': [parts[0], parts[1], parts[2], parts[3], parts[4]],
                'confidence': confidence,
                'area': area,
                'original_index': idx,
                'original_line': line,
                # Store extra fields if any (e.g. confidence score)
                'extra_parts': parts[5:] if len(parts) > 5 else []
            })
        except ValueError:
            # Skip lines that can't be parsed
            continue

    if not parsed_boxes:
        return []

    # Sort boxes: First by confidence score (descending). 
    # If confidence is equal (e.g. ground truths all have 1.0), sort based on priority_metric
    if priority_metric == "area":
        # Keep larger boxes first
        parsed_boxes.sort(key=lambda x: (x['confidence'], x['area']), reverse=True)
    elif priority_metric == "area_small":
        # Keep smaller boxes first
        parsed_boxes.sort(key=lambda x: (x['confidence'], -x['area']), reverse=True)
    else:
        # Keep original file order
        parsed_boxes.sort(key=lambda x: (x['confidence'], -x['original_index']), reverse=True)

    keep_boxes = []

    if class_agnostic:
        # Perform class-agnostic NMS (compare all boxes regardless of class)
        while parsed_boxes:
            best_box = parsed_boxes.pop(0)
            keep_boxes.append(best_box)
            
            remaining = []
            for b in parsed_boxes:
                iou = calculate_iou(best_box['box'], b['box'])
                if iou < iou_threshold:
                    remaining.append(b)
            parsed_boxes = remaining
    else:
        # Perform class-specific NMS (compare boxes of the same class only)
        # Group by class first
        class_groups: Dict[int, List[Dict[str, Any]]] = {}
        for b in parsed_boxes:
            cid = b['class_id']
            if cid not in class_groups:
                class_groups[cid] = []
            class_groups[cid].append(b)
            
        for cid, group in class_groups.items():
            while group:
                best_box = group.pop(0)
                keep_boxes.append(best_box)
                
                remaining = []
                for b in group:
                    iou = calculate_iou(best_box['box'], b['box'])
                    if iou < iou_threshold:
                        remaining.append(b)
                group = remaining

    # Sort the kept boxes by their original index to preserve original ordering structure
    keep_boxes.sort(key=lambda x: x['original_index'])
    
    # Format back to YOLO lines
    output_lines = []
    for b in keep_boxes:
        coords_str = " ".join(b['yolo_coords'])
        if b['extra_parts']:
            extra_str = " ".join(b['extra_parts'])
            output_lines.append(f"{coords_str} {extra_str}")
        else:
            output_lines.append(coords_str)
            
    return output_lines

def process_file(file_path: str, output_path: str, iou_threshold: float, class_agnostic: bool, priority_metric: str) -> tuple:
    """Processes a single file, removing duplicates and saving to output_path."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"[!] Error reading {file_path}: {e}")
        return 0, 0

    original_count = len([l for l in lines if l.strip()])
    cleaned_lines = clean_yolo_boxes(lines, iou_threshold, class_agnostic, priority_metric)
    cleaned_count = len(cleaned_lines)
    removed_count = original_count - cleaned_count

    try:
        # Create output directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(cleaned_lines) + ("\n" if cleaned_lines else ""))
    except Exception as e:
        print(f"[!] Error writing to {output_path}: {e}")
        return 0, 0

    return original_count, cleaned_count

def main():
    print("=" * 60)
    print("         YOLO BOUNDING BOX DEDUPLICATION TOOL (NMS)          ")
    print("=" * 60)
    
    # Try interactive input first if no arguments are provided
    if len(sys.argv) == 1:
        # Interactive Mode
        path = input("Enter path to file or directory of YOLO annotation txt files: ").strip()
        while not path or not os.path.exists(path):
            print("[!] Path does not exist. Please try again.")
            path = input("Enter path to file or directory of YOLO annotation txt files: ").strip()
            
        iou_input = input("Enter Overlap Threshold IoU (0.0 to 1.0, e.g. 0.5): ").strip()
        while True:
            try:
                iou_threshold = float(iou_input)
                if 0.0 <= iou_threshold <= 1.0:
                    break
                print("[!] Threshold must be between 0.0 and 1.0.")
            except ValueError:
                pass
            iou_input = input("Enter Overlap Threshold IoU (0.0 to 1.0): ").strip()
            
        class_agnostic_input = input("Remove overlap between different classes? (y/n, default 'n'): ").strip().lower()
        class_agnostic = class_agnostic_input == 'y'
        
        print("\nChoose priority metric (which box to keep when overlapping):")
        print("  1. Keep larger boxes (Default)")
        print("  2. Keep smaller boxes")
        print("  3. Keep original file order")
        choice = input("Enter option (1/2/3): ").strip()
        if choice == '2':
            priority_metric = "area_small"
        elif choice == '3':
            priority_metric = "original"
        else:
            priority_metric = "area"
            
        save_in_place_input = input("\nOverwrite original files? (y/n - choosing 'n' will save to a '_cleaned' folder, default 'n'): ").strip().lower()
        save_in_place = save_in_place_input == 'y'
        
    else:
        # CLI Mode
        parser = argparse.ArgumentParser(description="Clean overlapping YOLO bounding boxes using IoU NMS.")
        parser.add_argument("path", help="Path to a single YOLO text file or a directory containing text files.")
        parser.add_argument("-t", "--threshold", type=float, default=0.5, help="IoU overlap threshold (default: 0.5).")
        parser.add_argument("--agnostic", action="store_true", help="Perform class-agnostic NMS (de-duplicate across different classes).")
        parser.add_argument("--priority", choices=["area", "area_small", "original"], default="area", 
                            help="Priority metric when no confidence scores are present (default: area).")
        parser.add_argument("--in-place", action="store_true", help="Overwrite the original files instead of saving to a new directory.")
        
        args = parser.parse_args()
        path = args.path
        iou_threshold = args.threshold
        class_agnostic = args.agnostic
        priority_metric = args.priority
        save_in_place = args.in_place
        
        if not os.path.exists(path):
            print(f"[!] Input path '{path}' does not exist.")
            sys.exit(1)

    # Resolve output directory/file paths
    files_to_process = []
    if os.path.isfile(path):
        if not path.endswith('.txt'):
            print("[!] Warning: Selected file is not a .txt file. Proceeding anyway.")
            confirm = input("Continue? (y/n): ").strip().lower()
            if confirm != 'y':
                sys.exit(0)
        files_to_process.append(path)
    else:
        # Directory
        for root, _, files in os.walk(path):
            for file in files:
                if file.endswith('.txt') and file != "classes.txt":
                    files_to_process.append(os.path.join(root, file))
                    
    if not files_to_process:
        print("[!] No .txt label files found to process.")
        sys.exit(0)
        
    print(f"\n[*] Found {len(files_to_process)} file(s) to process.")
    print(f"[*] IoU Threshold: {iou_threshold}")
    print(f"[*] Class-agnostic mode: {class_agnostic}")
    print(f"[*] Priority metric: {priority_metric}")
    
    total_original = 0
    total_cleaned = 0
    processed_count = 0
    
    for f_path in files_to_process:
        if save_in_place:
            out_path = f_path
        else:
            # Create a parallel folder or suffix file path
            if os.path.isfile(path):
                dir_name, file_name = os.path.split(f_path)
                base_name, ext = os.path.splitext(file_name)
                out_path = os.path.join(dir_name, f"{base_name}_cleaned{ext}")
            else:
                # If directory, append '_cleaned' to the directory name
                rel_path = os.path.relpath(f_path, path)
                out_dir = path.rstrip(os.sep) + "_cleaned"
                out_path = os.path.join(out_dir, rel_path)
                
        orig, clean = process_file(f_path, out_path, iou_threshold, class_agnostic, priority_metric)
        total_original += orig
        total_cleaned += clean
        processed_count += 1
        
    removed = total_original - total_cleaned
    print("\n" + "=" * 60)
    print("                        SUMMARY OF RESULTS                    ")
    print("=" * 60)
    print(f"[*] Files processed:         {processed_count}")
    print(f"[*] Total original boxes:    {total_original}")
    print(f"[*] Total kept boxes:        {total_cleaned}")
    print(f"[*] Total boxes removed:     {removed} ({removed/total_original*100:.2f}% if total > 0 else 0)")
    if not save_in_place:
        output_loc = path + "_cleaned" if os.path.isdir(path) else os.path.dirname(path)
        print(f"[*] Cleaned files saved to:  {output_loc}")
    else:
        print("[*] Original files overwritten in-place.")
    print("=" * 60)

if __name__ == "__main__":
    main()
