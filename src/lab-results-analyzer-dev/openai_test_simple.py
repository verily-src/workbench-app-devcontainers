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
project_id = "wb-smart-cabbage-5940"

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

# Try different version aliases - some secrets use "live", others use "latest"
secret_client = secretmanager.SecretManagerServiceClient()
secret_name = f"{team_alias}openai-api-key"

# Try "live" first, then fall back to "latest"
openai_key = None
for version in ["live", "latest"]:
    try:
        name = f"projects/{project_id}/secrets/{secret_name}/versions/{version}"
        print(f"🔐 Trying to access secret: {name}")
        response = secret_client.access_secret_version(name=name)
        openai_key = response.payload.data.decode("UTF-8")
        print(f"✅ Successfully retrieved secret using version: {version}")
        break
    except Exception as e:
        print(f"⚠️  Version '{version}' not available: {e}")
        continue

if openai_key is None:
    print(f"\n❌ Could not retrieve secret from any version")
    print(f"   Secret name: {secret_name}")
    print(f"   Project ID: {project_id}")
    print(f"\n💡 Troubleshooting:")
    print(f"   1. Verify the secret exists: {secret_name}")
    print(f"   2. Check if you have access to the secret")
    print(f"   3. Verify the project ID is correct")
    print(f"   4. Check if the secret has any versions available")
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

