#!/usr/bin/env python3
"""
Export Qwen2.5-VL-3B-Instruct to OpenVINO FP16 IR.
No compression – lighter memory profile.
"""
from pathlib import Path
from optimum.intel import OVModelForVisualCausalLM
from transformers import AutoProcessor

MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "models" / "qwen2.5-vl-3b-fp16"

print("Loading processor…")
processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)

print("Exporting model to OpenVINO FP16 (this may take 10‑20 minutes)…")
model = OVModelForVisualCausalLM.from_pretrained(
    MODEL_ID,
    export=True,
    use_cache=True,
    trust_remote_code=True,
)
print("Saving FP16 model…")
model.save_pretrained(OUTPUT_DIR)
processor.save_pretrained(OUTPUT_DIR)
print(f"✅ FP16 model saved to {OUTPUT_DIR}")