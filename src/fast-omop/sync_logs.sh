#!/bin/bash                                           
# Sync FastOMOP traces to workspace GCS bucket
BUCKET_PATH="gs://${WORKSPACE_BUCKET}/fastomop-logs"                                                              
gsutil -m rsync -r /var/log/fastomop/ "${BUCKET_PATH}/"