import torch
import numpy as np
from typing import List
from schemas.detection import DetectionEvent, DetectionObject

class RFDETRDetector:
    def __init__(self, model_path: str, device="cuda"):
        # Assume a custom RF-DETR implementation loaded as a TorchScript or ONNX
        self.model = torch.jit.load(model_path)
        self.model.to(device)
        self.model.eval()
        self.device = device
        self.class_names = ["person", "helmet", "no-helmet", "fire", ...]

    def preprocess(self, frame: np.ndarray):
        # resize, normalize, etc.
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (640,640))
        img = torch.from_numpy(img).permute(2,0,1).float() / 255.0
        return img.unsqueeze(0).to(self.device)

    def predict(self, frame: np.ndarray) -> DetectionEvent:
        tensor = self.preprocess(frame)
        with torch.no_grad():
            output = self.model(tensor)
        # Parse output into a list of DetectionObject with normalized bboxes
        # ...
        return DetectionEvent(camera_id=..., frame_id=..., timestamp=..., objects=[...])