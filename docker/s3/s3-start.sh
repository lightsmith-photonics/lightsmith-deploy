#!/bin/sh
# Writes the SeaweedFS S3 identities from the environment, then starts a single-node server with
# the S3 gateway on :8333. Each product may only touch its own bucket.
set -eu

cat > /tmp/s3.json <<JSON
{
  "identities": [
    {
      "name": "community",
      "credentials": [{ "accessKey": "community", "secretKey": "${COMMUNITY_S3_SECRET}" }],
      "actions": ["Admin:lightsmith-community", "Read:lightsmith-community", "Write:lightsmith-community",
                  "List:lightsmith-community", "Tagging:lightsmith-community"]
    },
    {
      "name": "cloud",
      "credentials": [{ "accessKey": "cloud", "secretKey": "${CLOUD_S3_SECRET}" }],
      "actions": ["Admin:lightsmith-results", "Read:lightsmith-results", "Write:lightsmith-results",
                  "List:lightsmith-results", "Tagging:lightsmith-results"]
    }
  ]
}
JSON

exec /entrypoint.sh server -dir=/data -s3 -s3.port=8333 -s3.config=/tmp/s3.json -master.volumeSizeLimitMB=1024
