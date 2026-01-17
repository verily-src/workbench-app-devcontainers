#!/usr/bin/env python3
"""
Check Vertex AI Access Without Admin Permissions
This script checks what Vertex AI services are already available
without requiring API enablement permissions.
"""

import sys
import subprocess

print("="*70)
print("🔍 Checking Vertex AI Access (No Admin Required)")
print("="*70)

# Install package if needed
try:
    import google.cloud.aiplatform as aiplatform
except ImportError:
    print("Installing google-cloud-aiplatform...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-aiplatform"])
    import google.cloud.aiplatform as aiplatform

try:
    from google.auth import default
    credentials, project_id = default()
    print(f"\n✅ Authentication: SUCCESS")
    print(f"   Project: {project_id}")
    
    # Try different regions to see if Vertex AI is available anywhere
    regions_to_try = ["us-central1", "us-east1", "us-west1", "europe-west1", "asia-east1"]
    
    print("\n🌍 Testing Vertex AI access in different regions...")
    working_regions = []
    
    for region in regions_to_try:
        try:
            print(f"   Testing {region}...", end=" ")
            aiplatform.init(project=project_id, location=region)
            print("✅ Works!")
            working_regions.append(region)
        except Exception as e:
            error_msg = str(e).lower()
            if "api not enabled" in error_msg or "serviceusage" in error_msg:
                print("❌ API not enabled")
            elif "permission" in error_msg or "denied" in error_msg:
                print("❌ Permission denied")
            elif "not found" in error_msg:
                print("⚠️  Not available")
            else:
                print(f"⚠️  {str(e)[:50]}")
    
    if working_regions:
        print(f"\n✅ Vertex AI is available in: {', '.join(working_regions)}")
        print(f"\n💡 You can use Vertex AI! Try this region:")
        print(f"   aiplatform.init(project='{project_id}', location='{working_regions[0]}')")
    else:
        print("\n⚠️  Vertex AI API doesn't appear to be enabled in any region")
        print("\n💡 Next Steps:")
        print("   1. Ask your project administrator to enable:")
        print("      - Service Usage API")
        print("      - Vertex AI API")
        print("   2. Request the 'Vertex AI User' role:")
        print("      roles/aiplatform.user")
        print("   3. Or check if you have access to a different project")
    
    print("\n" + "="*70)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print("\n💡 Troubleshooting:")
    print("   - Check your GCP authentication")
    print("   - Verify you have access to the project")
    print("="*70)

