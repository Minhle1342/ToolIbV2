import os
import cv2
import numpy as np
import onnxruntime as ort

class YOLOInference:
    def __init__(self, model_path):
        self.model_path = model_path
        self.session = None
        self.input_name = None
        self.class_names = {}
        self.input_width = 640
        self.input_height = 640
        self.ensure_session()

    def ensure_session(self):
        if self.session is None and os.path.exists(self.model_path):
            try:
                self.session = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
                self.input_name = self.session.get_inputs()[0].name
                
                # Try to get input shape dynamically from model
                try:
                    input_shape = self.session.get_inputs()[0].shape
                    if len(input_shape) == 4:
                        h = input_shape[2]
                        w = input_shape[3]
                        if isinstance(h, int) and h > 0:
                            self.input_height = h
                        if isinstance(w, int) and w > 0:
                            self.input_width = w
                        print(f"Dynamic input shape detected: {self.input_width}x{self.input_height}")
                except Exception as shape_err:
                    print(f"Warning: Could not get input shape dynamically: {shape_err}")
                
                # Load class names from model metadata
                try:
                    meta = self.session.get_modelmeta().custom_metadata_map
                    if 'names' in meta:
                        import ast
                        self.class_names = ast.literal_eval(meta['names'])
                except Exception as meta_err:
                    print(f"Warning: Could not load class names from model metadata: {meta_err}")
            except Exception as e:
                print(f"Error loading ONNX session: {e}")

    def preprocess(self, image_path=None, target_size=None, img=None):
        if target_size is None:
            target_size = (self.input_width, self.input_height)
        # Load image
        if img is None:
            img = cv2.imread(image_path)
            if img is None:
                raise ValueError(f"Could not load image: {image_path}")

        h, w = img.shape[:2]
        
        # "Force" resize (squeeze) as requested
        img_resized = cv2.resize(img, target_size)
        
        # Preprocess: BGR -> RGB, float32, prompt -> 0-1
        blob = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        blob = blob.astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1) # CHW
        blob = np.expand_dims(blob, axis=0) # Batch dimension
        
        return blob, (w, h)

    def predict(self, image_path, conf_threshold=0.25, iou_threshold=0.45, region=None):
        self.ensure_session()
        if not self.session:
            return {'error': f'Model not found at {self.model_path}. Please ensure the file exists.'}

        img = cv2.imread(image_path)
        if img is None:
            return {'error': f"Could not load image: {image_path}"}
            
        full_h, full_w = img.shape[:2]
        offset_x = 0
        offset_y = 0
        
        if region:
            r_x = float(region.get('x', 0))
            r_y = float(region.get('y', 0))
            r_w = float(region.get('w', 1.0))
            r_h = float(region.get('h', 1.0))
            
            # Treat as normalized if values are <= 1.0 (since normalized coords are 0.0-1.0)
            if r_x <= 1.0 and r_y <= 1.0 and r_w <= 1.0 and r_h <= 1.0:
                rx = int(max(0, r_x * full_w))
                ry = int(max(0, r_y * full_h))
                rw = int(r_w * full_w)
                rh = int(r_h * full_h)
            else:
                rx = int(max(0, r_x))
                ry = int(max(0, r_y))
                rw = int(r_w)
                rh = int(r_h)
            
            rx = min(rx, full_w - 1)
            ry = min(ry, full_h - 1)
            rw = min(rw, full_w - rx)
            rh = min(rh, full_h - ry)
            
            if rw > 0 and rh > 0:
                img = img[ry:ry+rh, rx:rx+rw]
                offset_x = rx
                offset_y = ry

        # 1. Preprocess
        try:
            input_tensor, (orig_w, orig_h) = self.preprocess(img=img)
        except Exception as e:
            return {'error': str(e)}
        
        # 2. Inference
        outputs = self.session.run(None, {self.input_name: input_tensor})
        
        # 3. Postprocess
        # Attempt to handle different shapes. Setup usually (1, 4+nc, N)
        output = outputs[0]
        
        # Squeeze batch if present
        if output.ndim == 3:
            output = output[0] # (4+nc, N)
            
        # Check standard YOLO output layout
        # usually [cx, cy, w, h, score...]
        # If shape is (N, 4+nc), transpose isn't needed. 
        # But usually it is (channels, anchors) -> Transpose to (anchors, channels)
        if output.shape[0] < output.shape[1]: 
            output = output.transpose() # Now (N, 4+nc)
            
        rows = output.shape[0]
        boxes = []
        confidences = []
        class_ids = []

        # Find max scores
        # First 4 columns are box coords
        box_data = output[:, :4]
        scores_data = output[:, 4:]
        
        # Get max confidence and class index for each row
        class_scores = np.max(scores_data, axis=1)
        classes = np.argmax(scores_data, axis=1)
        
        # Filter by threshold
        mask = class_scores > conf_threshold
        
        filtered_boxes = box_data[mask]
        filtered_scores = class_scores[mask]
        filtered_classes = classes[mask]
        
        # Convert to XYWH (center to top-left) and Rescale
        # Model coords are in self.input_width x self.input_height
        sx = orig_w / float(self.input_width)
        sy = orig_h / float(self.input_height)
        
        for i in range(len(filtered_boxes)):
            cx, cy, w, h = filtered_boxes[i]
            
            # Convert center-wh to top-left-wh
            x = (cx - w/2)
            y = (cy - h/2)
            
            # Scale back to original
            x *= sx
            y *= sy
            w *= sx
            h *= sy
            
            boxes.append([x, y, w, h])
            confidences.append(float(filtered_scores[i]))
            class_ids.append(int(filtered_classes[i]))

        # NMS
        indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, iou_threshold)
        
        results = []
        if len(indices) > 0:
            for i in indices.flatten():
                x, y, w, h = boxes[i]
                
                # Convert Top-Left Absolute to Center Normalized
                # x, y, w, h are currently in pixels relative to orig_w, orig_h (cropped region)
                
                abs_x = x + offset_x
                abs_y = y + offset_y
                abs_w = w
                abs_h = h
                
                cx = (abs_x + abs_w / 2) / full_w
                cy = (abs_y + abs_h / 2) / full_h
                nw = abs_w / full_w
                nh = abs_h / full_h

                results.append({
                    'class_id': class_ids[i],
                    'x': float(cx),
                    'y': float(cy),
                    'w': float(nw),
                    'h': float(nh),
                    'conf': confidences[i]
                })
                
        return {'success': True, 'boxes': results}
