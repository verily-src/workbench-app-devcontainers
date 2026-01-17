#!/usr/bin/env python3
"""
Simple Vertex AI Connection Test
Quick test to verify Vertex AI access.
"""

import sys
import subprocess

print("="*70)
print("🔍 Quick Vertex AI Connection Test")
print("="*70)

# Install package if needed
try:
    import google.cloud.aiplatform as aiplatform
except ImportError:
    print("Installing google-cloud-aiplatform...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-aiplatform"])
    import google.cloud.aiplatform as aiplatform

# Test authentication and initialization
try:
    from google.auth import default
    credentials, project_id = default()
    print(f"\n✅ Authentication: SUCCESS")
    print(f"   Project: {project_id}")
    
    # Try to initialize Vertex AI
    region = "us-central1"  # Change to your region if needed
    aiplatform.init(project=project_id, location=region)
    print(f"✅ Vertex AI Initialization: SUCCESS")
    print(f"   Location: {region}")
    
    print("\n" + "="*70)
    print("🎉 All tests passed! You can use Vertex AI.")
    print("="*70)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print("\n💡 Troubleshooting:")
    print("   - Make sure Vertex AI API is enabled")
    print("   - Check that you have proper IAM permissions")
    print("   - Verify the region is correct")
    print("="*70)

