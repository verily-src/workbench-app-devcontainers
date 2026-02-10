#!/usr/bin/env python3
"""
Test script for OpenAI integration with GCP Secret Manager
Modified for php-product team
"""

# Install required packages
import subprocess
import sys

try:
    from google.cloud import secretmanager
    import openai
    print("✅ Packages already installed")
except ImportError:
    print("ℹ️  Installing packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "google-cloud-secret-manager", "openai"])
    from google.cloud import secretmanager
    import openai
    print("✅ Packages installed successfully!")

# ============================================================================
# CONFIGURATION: Your Project and Team
# ============================================================================
# Use this stanza when working in VWB Sandbox workspaces
project_id = "wb-smart-cabbage-5940"

# Your team alias
team_alias = "php-product-"

# Use this stanza when working with prod data. Uncomment both lines below.
# import subprocess
# project_id = subprocess.check_output("wb status --format=json | jq -r '.workspace.googleProjectId'", shell=True, text=True).strip()
# team_alias = ""

# ============================================================================
# Retrieve Secret and Initialize OpenAI Client
# ============================================================================

print("="*70)
print("🔐 OpenAI Integration Test")
print("="*70)
print(f"Project ID: {project_id}")
print(f"Team Alias: {team_alias}")
print(f"Secret Name: {team_alias}openai-api-key")
print("="*70)

# Construct secret path
name = f"projects/{project_id}/secrets/{team_alias}openai-api-key/versions/live"

print(f"\n📥 Retrieving secret from: {name}")

try:
    secret_client = secretmanager.SecretManagerServiceClient()
    response = secret_client.access_secret_version(name=name)
    openai_key = response.payload.data.decode("UTF-8")
    print("✅ Secret retrieved successfully!")
except Exception as e:
    print(f"❌ Error retrieving secret: {e}")
    print("\n💡 Troubleshooting:")
    print("   - Verify service account has access to the secret")
    print("   - Check that the secret path is correct")
    print("   - Ensure you're in the correct GCP project")
    raise

# Initialize OpenAI client
print("\n🤖 Initializing OpenAI client...")
try:
    client = openai.OpenAI(
        api_key=openai_key,
        base_url="https://us.api.openai.com/v1/",
    )
    print("✅ OpenAI client initialized!")
except Exception as e:
    print(f"❌ Error initializing OpenAI client: {e}")
    raise

# ============================================================================
# Test OpenAI API Call
# ============================================================================

print("\n" + "="*70)
print("🧪 Testing OpenAI API...")
print("="*70)

try:
    # Note: The original script used client.responses.create() which may not be correct
    # Using chat.completions.create() which is the standard OpenAI API
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
    
    print("\n✅ OpenAI API call successful!")
    print("\n📝 Response:")
    print("="*70)
    print(response.choices[0].message.content)
    print("="*70)
    
except Exception as e:
    print(f"❌ Error calling OpenAI API: {e}")
    print("\n💡 Note: If you see an error about 'responses' attribute, the original")
    print("   script may have used an incorrect API method. This script uses")
    print("   the standard chat.completions.create() method.")
    raise

print("\n" + "="*70)
print("✅ OpenAI Integration Test Complete!")
print("="*70)

