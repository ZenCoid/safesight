import time
import cv2
import numpy as np
import torch
import logging
from typing import List
from uuid import UUID
from schemas.detection import DetectionEvent, DetectionObject

logger = logging.getLogger(__name__)

class RFDETRDetector:
    def __init__(self, model_path: str, device="cuda"):
        self.model = torch.jit.load(model_path)
        self.model.to(device)
        self.model.eval()
        self.device = device
        self.class_names = ["person", "helmet", "no-helmet", "fire", "forklift"]
        logger.info(f"RF-DETR model loaded from {model_path}")

    def preprocess(self, frame: np.ndarray):
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = cv2.resize(frame, (640, 640))
        # Ensure contiguous memory for PyTorch
        frame = np.ascontiguousarray(frame)
        tensor = torch.from_numpy(frame).permute(2, 0, 1).float() / 255.0
        return tensor.unsqueeze(0).to(self.device)

    def predict(self, frame: np.ndarray, camera_id: UUID, frame_id: int) -> DetectionEvent:
        """
        Run inference and return a DetectionEvent.
        This is a stub – replace with actual model output parsing.
        """
        # tensor = self.preprocess(frame)
        # with torch.no_grad():
        #     output = self.model(tensor)
        logger.warning("predict() not implemented – returning empty DetectionEvent")
        return DetectionEvent(
            camera_id=camera_id,
            frame_id=frame_id,
            timestamp=time.time(),
            objects=[]
        )