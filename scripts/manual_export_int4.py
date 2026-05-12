#!/usr/bin/env python3
"""
Manual export of Qwen2.5-VL-3B-Instruct to OpenVINO INT4.
Bypasses optimum-cli bugs. Uses PyTorch + openvino + nncf directly.
"""
from pathlib import Path
import torch
from transformers import Qwen2_5VLForConditionalGeneration, AutoProcessor
import openvino as ov
import nncf

MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "models" / "qwen2.5-vl-3b-int4"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("Loading PyTorch model …")
# Load in float16 to save memory during tracing
model = Qwen2_5VLForConditionalGeneration.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float16,
    device_map="cpu",
    trust_remote_code=True,
)
model.eval()

processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)

# ---------------------------------------------------------------------
# 1. Export language model (main body)
# ---------------------------------------------------------------------
print("Exporting language model …")
lm = model.model  # Qwen2_5VLModel
# Example inputs: input_ids and attention_mask (batch size 1, sequence length 8)
input_ids = torch.ones((1, 8), dtype=torch.long)
attention_mask = torch.ones_like(input_ids)

# We need to pass position_ids too? The model handles them internally, but we trace with the encoder-decoder shape.
# Use a simple trace with dummy image features
# Actually, the language model expects inputs_embeds, so we can trace the backbone with input_ids.
lm_ir = ov.convert_model(
    lm,
    example_input={
        "input_ids": input_ids,
        "attention_mask": attention_mask,
    },
)
# Save uncompressed first (will compress later)
lm_xml = OUTPUT_DIR / "openvino_language_model.xml"
ov.save_model(lm_ir, lm_xml)
del lm_ir

# ---------------------------------------------------------------------
# 2. Export vision encoder
# ---------------------------------------------------------------------
print("Exporting vision encoder …")
vision_model = model.visual  # Qwen2_5VLVisionModel
# Dummy pixel values: shape (1, 3, image_height, image_width) – typical 336x336 resized
dummy_pixel_values = torch.zeros((1, 3, 336, 336), dtype=torch.float16)

# The vision model returns (image_embeds, dummy) – we trace the forward method
vision_ir = ov.convert_model(
    vision_model,
    example_input={"pixel_values": dummy_pixel_values},
)
ov.save_model(vision_ir, OUTPUT_DIR / "openvino_vision_embeddings_model.xml")
del vision_ir

# ---------------------------------------------------------------------
# 3. Export text embeddings
# ---------------------------------------------------------------------
print("Exporting text embeddings …")
embed_tokens = model.model.get_input_embeddings()  # torch.nn.Embedding
embed_ir = ov.convert_model(embed_tokens, example_input={"input": input_ids})
ov.save_model(embed_ir, OUTPUT_DIR / "openvino_text_embeddings_model.xml")
del embed_ir

# ---------------------------------------------------------------------
# 4. Apply INT4 weight compression to the language model
# ---------------------------------------------------------------------
print("Applying INT4 compression to language model …")
core = ov.Core()
compressed_lm = core.read_model(lm_xml)
compressed_lm = nncf.compress_weights(
    compressed_lm,
    mode=nncf.CompressWeightsMode.INT4_ASYM,
    group_size=-1,            # per-channel
    ratio=1.0,
)
ov.save_model(compressed_lm, lm_xml)  # overwrite original
del compressed_lm

# ---------------------------------------------------------------------
# 5. Copy processor files
# ---------------------------------------------------------------------
print("Copying tokenizer/configs …")
processor.save_pretrained(OUTPUT_DIR)

print("✅ Done. INT4 model saved to", OUTPUT_DIR)
print("You may now delete the PyTorch cache to free space.")