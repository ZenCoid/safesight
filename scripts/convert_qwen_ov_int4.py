#!/usr/bin/env python3
"""
Qwen2.5-VL-3B-Instruct → OpenVINO IR (INT4)
-------------------------------------------
Requires: optimum-intel, openvino, nncf
The converted model is saved to ./models/qwen2.5-vl-3b-int4/
"""

from pathlib import Path
from optimum.intel import OVModelForVisualCausalLM
from transformers import AutoProcessor

MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "models" / "qwen2.5-vl-3b-int4"

def main():
    print(f"Downloading and converting {MODEL_ID} …")
    # Load processor first (lightweight)
    processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)

    # Load model + export to OpenVINO with INT4 weight compression
    # This will auto-download, trace, and quantise in one call.
    model = OVModelForVisualCausalLM.from_pretrained(
        MODEL_ID,
        export=True,                     # create OpenVINO IR
        load_in_8bit=False,
        compression="int4_weight_only",  # 4‑bit integer weights
        use_cache=True,
        trust_remote_code=True,
    )

    # Save the full pipeline
    model.save_pretrained(OUTPUT_DIR)
    processor.save_pretrained(OUTPUT_DIR)
    print(f"✅ Model saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    main()