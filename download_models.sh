#!/bin/bash
BASE_URL="https://raw.githubusercontent.com/justadudewhohacks/face-api.js/master/weights"
FILES=(
    "tiny_face_detector_model-weights_manifest.json"
    "tiny_face_detector_model-shard1"
    "face_landmark_68_model-weights_manifest.json"
    "face_landmark_68_model-shard1"
    "face_expression_model-weights_manifest.json"
    "face_expression_model-shard1"
)

DEST_DIR="public/models"
mkdir -p "$DEST_DIR"

for file in "${FILES[@]}"; do
    url="$BASE_URL/$file"
    output="$DEST_DIR/$file"
    echo "Downloading $file..."
    curl -sS -o "$output" "$url"
done
echo "Download complete."
