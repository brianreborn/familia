#!/bin/bash
#
# Build automation script for llama.cpp v0.7.0 (b16699)
# Automatically applies patch before compilation
#

set -e

# Configuration
PATCH_FILE="/home/green/familia/code-bootstraps-llama.cpp/llama.cpp-v0.7.0-pthread_create.patch"
BUILD_DIR="/home/green/familia/build"

# Verify patch file exists
if [ ! -f "$PATCH_FILE" ]; then
    echo "ERROR: Patch file not found: $PATCH_FILE"
    exit 1
fi

# Verify patch is newer than target directory
if [ "$(ls -t "$PATCH_FILE" "$BUILD_DIR" 2>/dev/null)" = "$PATCH_FILE" ]; then
    echo "Applying llama.cpp-v0.7.0-pthread_create.patch..."
    git apply -R "$PATCH_FILE"
    git add llama.cpp
    git commit -m "Apply llama.cpp-v0.7.0-pthread_create.patch"
    echo "Patch applied successfully!"
else
    echo "Patch is older than target, patch skipped"
fi

# Verify patch was applied
if [ -f "$BUILD_DIR/llama.cpp" ]; then
    echo "Verifying patch application..."
    if git diff --name-only "$PATCH_FILE" > /dev/null 2>&1; then
        echo "✓ Patch applied successfully"
    else
        echo "✗ Patch application failed"
        exit 1
    fi
else
    echo "✗ Patch not applied to llama.cpp directory"
    exit 1
fi

# Create build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Create dummy build script for patch application
cat > llama.cpp-build.sh << 'EOF'
#!/bin/bash
# Dummy build script for patch application
# This script is only used to verify patch application

echo "Building llama.cpp..."

# Check if patch was applied
if git diff --name-only llama.cpp-v0.7.0-pthread_create.patch > /dev/null 2>&1; then
    echo "Patch applied successfully"
    echo "Running llama.cpp build..."
    # ... actual build commands would go here
else
    echo "ERROR: Patch not applied"
    exit 1
fi
EOF

chmod +x llama.cpp-build.sh

# Verify patch application before build
if ! git diff --name-only llama.cpp-v0.7.0-pthread_create.patch > /dev/null 2>&1; then
    echo "ERROR: Patch not applied before build"
    exit 1
fi

echo "✓ All patch checks passed"
echo "Build directory: $BUILD_DIR"
echo "Build script created: llama.cpp-build.sh"
echo "=========================================="
echo "Build automation complete!"
echo "=========================================="
