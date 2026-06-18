import os
import cv2
import numpy as np
import onnxruntime as ort

class YOLOInference:
    def __init__(self, model_path):
        self.model_path = model_path
        self.session = None
        self.input_name = None
        self.ensure_session()

    def ensure_session(self):
        if self.session is None and os.path.exists(self.model_path):
            try:
                self.session = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
                self.input_name = self.session.get_inputs()[0].name
            except Exception as e:
                print(f"Error loading ONNX session: {e}")

    def preprocess(self, image_path, target_size=(1280, 1280)):
        # Load image
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

    def predict(self, image_path, conf_threshold=0.25, iou_threshold=0.45):
        self.ensure_session()
        if not self.session:
            return {'error': f'Model not found at {self.model_path}. Please ensure the file exists.'}

        # 1. Preprocess
        input_tensor, (orig_w, orig_h) = self.preprocess(image_path)
        
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
        # Model coords are in 1280x1280
        sx = orig_w / 1280.0
        sy = orig_h / 1280.0
        
        for i in range(len(filtered_boxes)):
            cx, cy, w, h = filtered_boxes[i]
            
            # Un-squeeze coords
            # x_center * sx, y_center * sy ... 
            # Wait, if we squeezed the image, we just scale back independently.
            
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
                # x, y, w, h are currently in pixels relative to orig_w, orig_h
                
                cx = (x + w / 2) / orig_w
                cy = (y + h / 2) / orig_h
                nw = w / orig_w
                nh = h / orig_h

                results.append({
                    'class_id': class_ids[i],
                    'x': float(cx),
                    'y': float(cy),
                    'w': float(nw),
                    'h': float(nh),
                    'conf': confidences[i]
                })
                
        return {'success': True, 'boxes': results}
