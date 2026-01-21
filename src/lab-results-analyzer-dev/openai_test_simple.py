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

name = f"projects/{project_id}/secrets/{team_alias}openai-api-key/versions/live"

secret_client = secretmanager.SecretManagerServiceClient()

openai_key = secret_client.access_secret_version(name=name).payload.data.decode("UTF-8")

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

