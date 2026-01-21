#!/usr/bin/env python3
"""
OpenAI test script using the secret that IT team actually created: si-ops-openai-api-key
"""

# Install packages
import subprocess
import sys

try:
    from google.cloud import secretmanager
    import openai
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-secret-manager", "openai"])
    from google.cloud import secretmanager
    import openai

# Auto-detect project ID from environment
try:
    project_id = subprocess.check_output("wb status --format=json | jq -r '.workspace.googleProjectId'", shell=True, text=True).strip()
    print(f"✅ Auto-detected project ID: {project_id}")
except:
    project_id = "wb-smart-cabbage-5940"
    print(f"⚠️  Using hardcoded project ID: {project_id}")

# Use the secret name that IT team actually created
secret_name = "si-ops-openai-api-key"  # This is what IT team set up

secret_client = secretmanager.SecretManagerServiceClient()

# Try "latest" first (more common), then "live"
openai_key = None
last_error = None

for version in ["latest", "live"]:
    try:
        name = f"projects/{project_id}/secrets/{secret_name}/versions/{version}"
        print(f"🔐 Trying to access secret: {name}")
        response = secret_client.access_secret_version(name=name)
        openai_key = response.payload.data.decode("UTF-8")
        print(f"✅ Successfully retrieved secret using version: {version}")
        break
    except Exception as e:
        last_error = e
        if version == "latest":
            print(f"⚠️  Version 'latest' not available, trying 'live'...")
        else:
            print(f"⚠️  Version '{version}' not available: {e}")

if openai_key is None:
    print(f"\n❌ Could not retrieve secret from any version")
    print(f"   Secret name: {secret_name}")
    print(f"   Project ID: {project_id}")
    print(f"\n💡 This is the secret that IT team created.")
    print(f"   Make sure your service account has access to it.")
    raise Exception(f"Failed to retrieve secret {secret_name}")

client = openai.OpenAI(
    api_key=openai_key,
    base_url="https://us.api.openai.com/v1/",
)

print("\n🤖 Testing OpenAI API...")
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {
            "role": "system",
            "content": "You are a friendly walleye fishing guide from Brainerd Minnesota."
        },
        {
            "role": "user",
            "content": "What is the best way to distribute OpenAI keys to users across teams?"
        }
    ],
    max_tokens=500
)

print("\n" + "="*70)
print("📝 OpenAI Response:")
print("="*70)
print(response.choices[0].message.content)
print("="*70)

