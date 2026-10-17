#!/usr/bin/env bash
set -euo pipefail

# Usage: add-model.sh <role> <path-to-gguf>
# Updates models-manifest.json and config/models-preset.ini.

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <role> <path-to-gguf>"
  exit 1
fi

ROLE="$1"
MODEL_PATH="$2"

# Resolve absolute path
if ! ABS_PATH=$(realpath "$MODEL_PATH" 2>/dev/null); then
  echo "Error: cannot resolve path $MODEL_PATH"
  exit 1
fi
if [[ ! -f "$ABS_PATH" ]]; then
  echo "Error: file $ABS_PATH does not exist"
  exit 1
fi

# Compute sha256 and size
SHA256=$(sha256sum "$ABS_PATH" | awk '{print $1}')
BYTES=$(stat -c%s "$ABS_PATH")
FILE_NAME=$(basename "$ABS_PATH")

# Determine repo and revision placeholders for local manual entries
REPO="local/manual"
REVISION="manual"
QUANT="unknown"
LICENSE="unknown"
CTX=8192
PICK="default"

# Append to models-manifest.json using Python for safety
python3 - <<PY
import json, pathlib, sys
manifest_path = pathlib.Path('code-bootstraps-llama.cpp/config/models-manifest.json')
with manifest_path.open('r', encoding='utf-8') as f:
    data = json.load(f)
new_entry = {
    "role": ROLE,
    "pick": PICK,
    "repo": REPO,
    "revision": REVISION,
    "file": FILE_NAME,
    "quant": QUANT,
    "bytes": int($BYTES),
    "sha256": "$SHA256",
    "license": LICENSE,
    "ctx": $CTX,
    "tested": False
}
# Append if not already present (same role & file)
if not any(e.get('role') == ROLE and e.get('file') == FILE_NAME for e in data.get('candidates', [])):
    data.setdefault('candidates', []).append(new_entry)
    with manifest_path.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, sort_keys=False)
    print('Added entry to models-manifest.json')
else:
    print('Entry already exists in models-manifest.json')
PY

# Update models-preset.ini
PRESET_PATH="code-bootstraps-llama.cpp/config/models-preset.ini"
REL_PATH=${ABS_PATH#/home/green/familia/}
# Use awk to insert or update model line under the appropriate section
awk -v role="$ROLE" -v model="$REL_PATH" '\
    BEGIN {section=""; updated=0} \
    /^\[.*\]$/ {section=tolower($0); next} \
    $0 ~ "^model[[:space:]]*=" && tolower(section) == "[" role "]" {print "model = " model; updated=1; next} \
    {print} \
    END {if (updated==0) {print "[" role "]"; print "model = " model}}' "$PRESET_PATH" > "$PRESET_PATH.tmp" && mv "$PRESET_PATH.tmp" "$PRESET_PATH"

echo "Updated $PRESET_PATH"
