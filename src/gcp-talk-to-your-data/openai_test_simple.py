#!/usr/bin/env python3
"""
Simple OpenAI test script - modified for php-product team
Based on IT team's original script
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

# Use this stanza when working in VWB Sandbox workspaces. Comment out if using prod data.
# project_id = "wb-smart-cabbage-5940"  # Project name
# Or use numeric project ID if needed:
# project_id = "579784059968"  # Numeric project ID (from error message)

# Auto-detect project ID from environment (recommended)
import subprocess
import os

# Try to get project ID from Workbench environment
try:
    project_id = subprocess.check_output("wb status --format=json | jq -r '.workspace.googleProjectId'", shell=True, text=True).strip()
    print(f"✅ Auto-detected project ID: {project_id}")
except:
    # Fallback to hardcoded project ID
    project_id = "wb-smart-cabbage-5940"
    print(f"⚠️  Using hardcoded project ID: {project_id}")
    print(f"   (If you see errors, try using numeric project ID: 579784059968)")

# Then choose your team alias.
team_alias = "php-product-"

# team_alias = "ml-platform-test-"
# team_alias = "compbio-"
# team_alias = "it-team-"
# team_alias = "participant-ops-"
# team_alias = "platform-ds-"
# team_alias = "registries-rwd-"
# team_alias = "science-team-"

# Use this stanza when working with prod data. Uncomment both lines below.
# import subprocess
# project_id = subprocess.check_output("wb status --format=json | jq -r '.workspace.googleProjectId'", shell=True, text=True).strip()
# team_alias = ""

# Try different version aliases - try "latest" first (more common), then "live"
secret_client = secretmanager.SecretManagerServiceClient()
secret_name = f"{team_alias}openai-api-key"

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
        error_msg = str(e)
        # Don't print error for "live" if we're going to try "latest" next
        if version == "latest":
            print(f"⚠️  Version 'latest' not available, trying 'live'...")
        else:
            print(f"⚠️  Version '{version}' not available: {error_msg}")

if openai_key is None:
    print(f"\n❌ Could not retrieve secret from any version")
    print(f"   Secret name: {secret_name}")
    print(f"   Project ID: {project_id}")
    print(f"   Last error: {last_error}")
    print(f"\n💡 Troubleshooting:")
    print(f"   1. Verify the secret exists: {secret_name}")
    print(f"   2. Check if you have access to the secret")
    print(f"   3. Verify the project ID is correct: {project_id}")
    print(f"   4. The secret might not exist yet - ask IT team to create it")
    print(f"   5. Check available versions in GCP Console → Secret Manager")
    
    # Try to list the secret to see if it exists
    try:
        print(f"\n🔍 Checking if secret exists...")
        parent = f"projects/{project_id}"
        secret_path = f"{parent}/secrets/{secret_name}"
        secret = secret_client.get_secret(name=secret_path)
        print(f"✅ Secret exists! Checking available versions...")
        
        # List versions
        versions = secret_client.list_secret_versions(parent=secret_path)
        version_list = list(versions)
        if version_list:
            print(f"   Available versions:")
            for v in version_list:
                print(f"   - {v.name.split('/')[-1]}")
        else:
            print(f"   ⚠️  No versions found for this secret")
    except Exception as check_error:
        print(f"   ❌ Secret does not exist or you don't have access: {check_error}")
    
    raise Exception(f"Failed to retrieve secret {secret_name} from project {project_id}")

client = openai.OpenAI(
    api_key=openai_key,
    base_url="https://us.api.openai.com/v1/",
)

# Note: The original script used client.responses.create() which may not be the correct API
# Using chat.completions.create() which is the standard OpenAI API method
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

print(response.choices[0].message.content)

