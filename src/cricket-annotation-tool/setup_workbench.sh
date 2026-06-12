#!/bin/bash
# Quick setup script for Verily Workbench

set -e

echo "🏏 Cricket Annotation Tool - Workbench Setup"
echo "============================================"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
pip install -q Flask Werkzeug

# Check for images
IMAGE_DIR="../data/cricket_images"
if [ -d "$IMAGE_DIR" ]; then
    IMAGE_COUNT=$(find $IMAGE_DIR -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.gif" \) 2>/dev/null | wc -l | tr -d ' ')

    if [ "$IMAGE_COUNT" -gt 0 ]; then
        echo "✓ Found $IMAGE_COUNT images in $IMAGE_DIR"
    else
        echo "⚠️  No images found in $IMAGE_DIR"
        echo ""
        echo "Add images via:"
        echo "  1. Workbench UI: Upload button → data/cricket_images/"
        echo "  2. GCS: gsutil cp gs://bucket/* $IMAGE_DIR/"
        echo ""
        read -p "Continue anyway? (y/n): " continue
        if [ "$continue" != "y" ]; then
            exit 1
        fi
    fi
else
    echo "⚠️  Image directory not found: $IMAGE_DIR"
    mkdir -p $IMAGE_DIR
    echo "✓ Created $IMAGE_DIR"
    echo ""
    echo "Please upload images to this directory and re-run this script"
    exit 1
fi

echo ""
echo "🚀 Starting annotation server..."
echo ""

# Start server
python app_demo.py &
SERVER_PID=$!

sleep 3

# Check if running
if ps -p $SERVER_PID > /dev/null; then
    echo "✓ Server started successfully!"
    echo ""
    echo "================================================"
    echo "ACCESS THE TOOL:"
    echo "================================================"
    echo ""
    echo "Option 1 (Recommended): Workbench Proxy"
    echo "  → Click the Web Preview button in Workbench"
    echo "  → Or go to: /proxy/8080/"
    echo ""
    echo "Option 2: Direct URL"
    echo "  → https://[YOUR-NOTEBOOK-ID]-8080.notebooks.googleusercontent.com"
    echo ""
    echo "================================================"
    echo "TO STOP THE SERVER:"
    echo "================================================"
    echo "  kill $SERVER_PID"
    echo "  or: pkill -f app_demo.py"
    echo ""
    echo "Server logs: /tmp/annotation_demo.log"
    echo "================================================"
    echo ""
    echo "Happy annotating! 🎨"
else
    echo "❌ Server failed to start"
    echo "Check logs: cat /tmp/annotation_demo.log"
    exit 1
fi
