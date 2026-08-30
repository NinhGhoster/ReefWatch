#!/usr/bin/env python3
"""
ShipRSImageNet Ship Detector — Fine-grained vessel detection on satellite imagery.

Uses Cascade Mask R-CNN (ResNet-50 + FPN) trained on ShipRSImageNet Level-3
(50 vessel classes) to detect and classify ships in Sentinel-2 optical imagery.
Standalone PyTorch implementation.
"""

import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch
from torchvision.models.detection import FasterRCNN
from torchvision.models.detection.rpn import AnchorGenerator
from torchvision.models.detection.backbone_utils import resnet_fpn_backbone
from torchvision import transforms

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
MODELS_DIR = os.path.join(BASE_DIR, "models")
IMAGERY_DIR = os.path.join(BASE_DIR, "imagery_history")
DATA_DIR = os.path.join(BASE_DIR, "data")

MODEL_FILE = os.path.join(MODELS_DIR, "cascade_mask_rcnn_r50_fpn_100e_ShipRSImageNet_Level3_epoch_100.pth")
CLASSES_FILE = os.path.join(MODELS_DIR, "ship_classes.json")
DETECTIONS_LOG = os.path.join(BASE_DIR, "ship_detections.jsonl")
TARGET_FEATURES = os.path.join(DATA_DIR, "target_features.json")

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# ---------------------------------------------------------------------------
# Ship class taxonomy
# ---------------------------------------------------------------------------

def load_ship_classes():
    with open(CLASSES_FILE) as f:
        data = json.load(f)
    classes = {c["id"]: c for c in data["classes"]}
    categories = data["categories"]
    class_names = tuple(c["name"] for c in data["classes"])
    return classes, categories, class_names

SHIP_CLASSES, SHIP_CATEGORIES, CLASS_NAMES = load_ship_classes()
NUM_CLASSES = 50

# ---------------------------------------------------------------------------
# Standalone PyTorch Model Loader
# ---------------------------------------------------------------------------

def _build_model():
    backbone = resnet_fpn_backbone(backbone_name="resnet50", weights=None)
    anchor_sizes = ((32,), (64,), (128,), (256,), (512,))
    aspect_ratios = ((0.5, 1.0, 2.0),) * 5
    anchor_generator = AnchorGenerator(sizes=anchor_sizes, aspect_ratios=aspect_ratios)

    num_classes_with_bg = NUM_CLASSES + 1

    model = FasterRCNN(
        backbone,
        num_classes=num_classes_with_bg,
        rpn_anchor_generator=anchor_generator,
        box_score_thresh=0.01,
        box_nms_thresh=0.5,
        box_detections_per_img=100,
        min_size=400,
        max_size=1333,
    )

    in_features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor.cls_score = torch.nn.Linear(in_features, num_classes_with_bg)
    model.roi_heads.box_predictor.bbox_pred = torch.nn.Linear(in_features, 4)

    orig_postprocess = model.roi_heads.postprocess_detections

    def _patched_postprocess(class_logits, box_regression, proposals, image_shapes):
        num_cls = class_logits.shape[-1]
        if box_regression.shape[-1] == 4:
            box_regression = box_regression.unsqueeze(1).expand(-1, num_cls, -1)
            box_regression = box_regression.reshape(-1, num_cls * 4)
        return orig_postprocess(class_logits, box_regression, proposals, image_shapes)

    model.roi_heads.postprocess_detections = _patched_postprocess
    return model

def _remap_state_dict(mmdet_sd):
    new_sd = {}
    for k, v in mmdet_sd.items():
        nk = None
        if k.startswith("backbone."):
            nk = k.replace("backbone.", "backbone.body.", 1)
        elif k.startswith("neck.lateral_convs."):
            parts = k.split(".")
            nk = f"backbone.fpn.inner_blocks.{parts[2]}.{'.'.join(parts[4:])}"
        elif k.startswith("neck.fpn_convs."):
            parts = k.split(".")
            nk = f"backbone.fpn.layer_blocks.{parts[2]}.{'.'.join(parts[4:])}"
        elif k.startswith("rpn_head.rpn_conv."):
            nk = k.replace("rpn_head.rpn_conv.", "rpn.head.conv.0.0.")
        elif k.startswith("rpn_head.rpn_cls."):
            nk = k.replace("rpn_head.rpn_cls.", "rpn.head.cls_logits.")
        elif k.startswith("rpn_head.rpn_reg."):
            nk = k.replace("rpn_head.rpn_reg.", "rpn.head.bbox_pred.")
        elif k.startswith("roi_head.bbox_head.2.shared_fcs.0."):
            nk = f"roi_heads.box_head.fc6.{k.split('shared_fcs.0.')[1]}"
        elif k.startswith("roi_head.bbox_head.2.shared_fcs.1."):
            nk = f"roi_heads.box_head.fc7.{k.split('shared_fcs.1.')[1]}"
        elif k.startswith("roi_head.bbox_head.2.fc_cls."):
            nk = f"roi_heads.box_predictor.cls_score.{k.split('fc_cls.')[1]}"
        elif k.startswith("roi_head.bbox_head.2.fc_reg."):
            nk = f"roi_heads.box_predictor.bbox_pred.{k.split('fc_reg.')[1]}"
        if nk:
            new_sd[nk] = v
    return new_sd

_model_cache = None

def load_model():
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    print(f"🔧 Loading ShipRSImageNet Cascade Mask R-CNN...", flush=True)
    model = _build_model()
    
    ckpt = torch.load(MODEL_FILE, map_location="cpu", weights_only=False)
    remapped = _remap_state_dict(ckpt["state_dict"])
    
    missing, unexpected = model.load_state_dict(remapped, strict=False)
    loaded = len(remapped) - len(unexpected)
    print(f"   ✅ Loaded {loaded} parameter tensors. CPU device.", flush=True)

    model.eval()
    _model_cache = model
    return model

# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def detect_ships(model, image_path, confidence=0.3):
    img = Image.open(image_path).convert("RGB")
    w_orig, h_orig = img.size

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    img_tensor = transform(img).unsqueeze(0)

    with torch.no_grad():
        outputs = model(img_tensor)

    output = outputs[0]
    detections = []
    edge_margin = 8  # Ignore edge detections (usually land)

    for i in range(len(output["scores"])):
        score = float(output["scores"][i])
        if score < confidence:
            continue

        cls_id = int(output["labels"][i]) - 1
        if cls_id < 0 or cls_id >= NUM_CLASSES:
            continue

        x1, y1, x2, y2 = output["boxes"][i].tolist()

        # Edge Filter
        at_left = x1 < edge_margin
        at_top = y1 < edge_margin
        at_right = x2 > (w_orig - edge_margin)
        at_bottom = y2 > (h_orig - edge_margin)
        if sum([at_left, at_top, at_right, at_bottom]) >= 1:
            continue

        bw, bh = x2 - x1, y2 - y1
        if bw < 2 or bh < 2:
            continue

        cls_info = SHIP_CLASSES.get(cls_id, {"name": f"class_{cls_id}", "category": "Unknown", "severity": "low"})
        
        # We also want to skip 'Dock' or 'Infrastructure' which is not a vessel
        if cls_info["category"] == "Infrastructure":
            continue

        detections.append({
            "class_id": cls_id,
            "class_name": cls_info["name"],
            "category": cls_info["category"],
            "severity": cls_info["severity"],
            "confidence": round(score, 4),
            "bbox_xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            "center_pixel": [round((x1 + x2) / 2, 1), round((y1 + y2) / 2, 1)],
            "bbox_width_px": round(bw, 1),
            "bbox_height_px": round(bh, 1),
        })

    detections.sort(key=lambda d: d["confidence"], reverse=True)
    return detections

def check_cloud_cover(image_path, max_cloud_pct=40.0):
    try:
        from cloud_filter import calculate_cloud_cover, detect_cloud_mask
        img = np.array(Image.open(image_path).convert("RGB"))
        cloud_mask = detect_cloud_mask(img)
        cloud_pct = calculate_cloud_cover(cloud_mask)
        return cloud_pct > max_cloud_pct, round(cloud_pct, 1)
    except Exception:
        return False, 0.0

def load_features():
    with open(TARGET_FEATURES) as f:
        return json.load(f)

def pixel_to_latlon(cx, cy, img_w, img_h, feat_lat, feat_lon, gsd_m=10.0):
    dx_m = (cx - img_w / 2) * gsd_m
    dy_m = (img_h / 2 - cy) * gsd_m
    lat_per_m = 1.0 / 111320.0
    lon_per_m = 1.0 / (111320.0 * np.cos(np.radians(feat_lat)))
    return round(feat_lat + dy_m * lat_per_m, 6), round(feat_lon + dx_m * lon_per_m, 6)

CATEGORY_COLORS = {
    "Military":       (239,  68,  68),   # Red
    "Auxiliary":      (249, 115,  22),   # Orange
    "Merchant":       ( 59, 130, 246),   # Blue
    "Civilian":       ( 34, 197,  94),   # Green
    "Infrastructure": (107, 114, 128),   # Gray
    "Unknown":        (168,  85, 247),   # Purple
}

def annotate_image(image_path, detections, output_path=None):
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except:
        font = ImageFont.load_default()

    for det in detections:
        x1, y1, x2, y2 = det["bbox_xyxy"]
        color = CATEGORY_COLORS.get(det.get("category", "Unknown"), (168, 85, 247))
        label = f"{det['class_name']} {det['confidence']:.0%}"

        for offset in range(2):
            draw.rectangle([x1 - offset, y1 - offset, x2 + offset, y2 + offset], outline=color)

        bbox_text = draw.textbbox((x1, y1 - 16), label, font=font)
        draw.rectangle([bbox_text[0] - 2, bbox_text[1] - 2, bbox_text[2] + 2, bbox_text[3] + 2], fill=color)
        draw.text((x1, y1 - 16), label, fill=(255, 255, 255), font=font)

    if output_path is None:
        stem = Path(image_path).stem
        output_path = os.path.join(IMAGERY_DIR, f"{stem}_ships.png")

    img.save(output_path)
    return output_path

def extract_date_from_filename(filename):
    stem = Path(filename).stem
    for part in stem.split("_"):
        if len(part) == 10 and part[4:5] == "-" and part[7:8] == "-":
            return part
    return None

def process_image(model, image_path, feature_key=None, feature_info=None, confidence=0.3, visualize=False):
    basename = os.path.basename(image_path)
    too_cloudy, cloud_pct = check_cloud_cover(image_path)
    if too_cloudy:
        print(f"  ☁️  {basename}: {cloud_pct}% cloud — skipped", flush=True)
        return None

    t0 = time.time()
    detections = detect_ships(model, image_path, confidence)
    elapsed = time.time() - t0

    if feature_info and detections:
        img = Image.open(image_path)
        for det in detections:
            lat, lon = pixel_to_latlon(det["center_pixel"][0], det["center_pixel"][1], img.size[0], img.size[1],
                                       feature_info.get("lat", 0), feature_info.get("lon", 0))
            det["estimated_lat"], det["estimated_lon"] = lat, lon

    vis_path = annotate_image(image_path, detections) if visualize and detections else None

    mil = sum(1 for d in detections if d["category"] == "Military")
    merch = sum(1 for d in detections if d["category"] in ("Merchant", "Civilian"))
    aux = sum(1 for d in detections if d["category"] == "Auxiliary")

    if detections:
        icon = "⚔️" if mil > 0 else "🚢"
        cls_str = ", ".join(f"{d['class_name']}({d['confidence']:.0%})" for d in detections[:3])
        print(f"  {icon} {basename}: {len(detections)} ship(s) [{cls_str}...] ({elapsed:.1f}s)", flush=True)
    else:
        print(f"  🌊 {basename}: no ships ({elapsed:.1f}s, cloud={cloud_pct}%)", flush=True)

    record = {
        "image_path": image_path,
        "feature_key": feature_key or "",
        "feature_name": feature_info.get("name", feature_key) if feature_info else feature_key,
        "date": extract_date_from_filename(image_path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cloud_pct": cloud_pct,
        "inference_time_s": round(elapsed, 2),
        "detections_count": len(detections),
        "military_count": mil,
        "merchant_count": merch,
        "auxiliary_count": aux,
        "detections": detections,
    }
    if vis_path: record["visualization"] = vis_path
    return record

def find_sentinel2_images(feature_key=None):
    results = []
    if not os.path.isdir(IMAGERY_DIR): return results
    for fname in sorted(os.listdir(IMAGERY_DIR)):
        if "_sentinel2_" in fname and fname.endswith(".png") and "_diff_" not in fname and "_ships" not in fname:
            fkey = fname.split("_sentinel2_")[0]
            if not feature_key or fkey == feature_key:
                results.append((os.path.join(IMAGERY_DIR, fname), fkey))
    return results

def run_detection(args):
    model = load_model()
    features_data = load_features()
    
    feature_lookup = {f["key"]: f for f in features_data if "key" in f}

    if args.image: images = [(args.image, args.feature or "unknown")]
    elif args.all or args.feature: images = find_sentinel2_images(args.feature)
    else:
        print("No images specified.")
        return

    if args.limit and args.limit > 0: images = images[:args.limit]
    if not images:
        print("No Sentinel-2 images found.")
        return

    print(f"\n🚢 Ship Detection — {len(images)} images to process")
    
    total_ships, total_military = 0, 0
    records = []

    for img_path, fkey in images:
        record = process_image(model, img_path, fkey, feature_lookup.get(fkey), args.confidence, args.visualize)
        if record:
            records.append(record)
            total_ships += record["detections_count"]
            total_military += record["military_count"]
            with open(DETECTIONS_LOG, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")

    print(f"\n{'='*60}\n  📊 Summary: {len(records)} imgs, {total_ships} ships ({total_military} military)\n{'='*60}\n")
    return records

def main():
    parser = argparse.ArgumentParser(description="ShipRSImageNet Ship Detector")
    parser.add_argument("--all", action="store_true", help="Process all features")
    parser.add_argument("--feature", type=str, help="Process single feature key")
    parser.add_argument("--image", type=str, help="Process single image file")
    parser.add_argument("--confidence", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--visualize", action="store_true", help="Generate annotated images")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of images")
    args = parser.parse_args()
    run_detection(args)

if __name__ == "__main__":
    main()
