#!/usr/bin/env python3
"""
Check which Gemini/Generative AI models are available in your project.
"""

import sys
import subprocess

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    from google.auth import default
except ImportError:
    print("Installing packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-aiplatform"])
    import vertexai
    from vertexai.generative_models import GenerativeModel
    from google.auth import default

creds, project = default()
regions = ["us-central1", "us-east1", "us-west1"]

print("="*70)
print("🔍 Checking Available Generative AI Models")
print("="*70)
print(f"Project: {project}")
print()

model_names = [
    "gemini-pro",
    "gemini-1.5-pro", 
    "gemini-1.0-pro",
    "gemini-1.5-flash",
    "text-bison@001",
    "chat-bison@001",
]

for region in regions:
    print(f"\n🌍 Region: {region}")
    print("-" * 70)
    vertexai.init(project=project, location=region)
    
    available_models = []
    for model_name in model_names:
        try:
            model = GenerativeModel(model_name)
            # Quick test
            response = model.generate_content("test")
            available_models.append(model_name)
            print(f"  ✅ {model_name}")
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "not found" in error_msg.lower():
                print(f"  ❌ {model_name} - Not available")
            elif "permission" in error_msg.lower() or "denied" in error_msg.lower():
                print(f"  ⚠️  {model_name} - Permission denied")
            else:
                print(f"  ⚠️  {model_name} - {error_msg[:60]}")
    
    if available_models:
        print(f"\n  💡 Available models in {region}: {', '.join(available_models)}")
        break

print("\n" + "="*70)
if available_models:
    print(f"✅ Use this model: {available_models[0]}")
    print(f"   Update your script with: GenerativeModel('{available_models[0]}')")
else:
    print("❌ No models available. You may need to:")
    print("   1. Enable Generative AI API")
    print("   2. Request access to Gemini models")
    print("   3. Check IAM permissions")
print("="*70)

