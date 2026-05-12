#!/usr/bin/env python3
"""
Compress the exported FP16 OpenVINO model to INT4 weights using NNCF.
Works directly on the OpenVINO IR files – no optimum wrapper needed.
"""
from pathlib import Path
import openvino as ov
import nncf

FP16_DIR = Path(__file__).resolve().parent.parent / "models" / "qwen2.5-vl-3b-fp16"
INT4_DIR = Path(__file__).resolve().parent.parent / "models" / "qwen2.5-vl-3b-int4"

# Find the model XML file (there should be exactly one)
xml_files = list(FP16_DIR.glob("*.xml"))
if not xml_files:
    raise FileNotFoundError(f"No OpenVINO model found in {FP16_DIR}")
model_xml = str(xml_files[0])

print(f"Loading model from {model_xml}")
core = ov.Core()
model = core.read_model(model_xml)

print("Applying INT4 weight compression (this may take a few minutes) …")
compressed_model = nncf.compress_weights(model, mode=nncf.CompressWeightsMode.INT4_ASYM)

print(f"Saving INT4 model to {INT4_DIR}")
INT4_DIR.mkdir(parents=True, exist_ok=True)
ov.save_model(compressed_model, str(INT4_DIR / xml_files[0].name))

# Also copy tokenizer and processor files from FP16 directory
for f in FP16_DIR.iterdir():
    if f.suffix not in (".xml", ".bin"):
        dest = INT4_DIR / f.name
        if not dest.exists():
            dest.write_bytes(f.read_bytes())

print("✅ INT4 model saved.")