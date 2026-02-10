#!/usr/bin/env python3
"""
Quick script to install required packages for OpenAI integration
Run this in a notebook cell or terminal
"""

import subprocess
import sys

packages = [
    "google-cloud-secret-manager",
    "openai"
]

print("Installing packages...")
for package in packages:
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package])
        print(f"✅ {package} installed")
    except Exception as e:
        print(f"❌ Error installing {package}: {e}")

print("\n✅ All packages installed!")

