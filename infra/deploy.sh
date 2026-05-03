#!/usr/bin/env bash
# Build the image, push to ECR, and update the Lambda function.
#
# Required env vars:
#   AWS_REGION       e.g. us-east-1
#   AWS_ACCOUNT_ID   12-digit AWS account id
#   ECR_REPO         e.g. workout-log
#   LAMBDA_NAME      e.g. workout-log
#
# One-time setup (bucket, ECR repo, IAM role, Lambda function, Function URL)
# is documented in the README and is NOT performed by this script.

set -euo pipefail

: "${AWS_REGION:?AWS_REGION is required}"
: "${AWS_ACCOUNT_ID:?AWS_ACCOUNT_ID is required}"
: "${ECR_REPO:?ECR_REPO is required}"
: "${LAMBDA_NAME:?LAMBDA_NAME is required}"

REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE_URI="${REGISTRY}/${ECR_REPO}:latest"

echo ">> Logging in to ECR ${REGISTRY}"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

echo ">> Building image"
docker build --platform linux/amd64 -t "${ECR_REPO}:latest" .

echo ">> Tagging and pushing ${IMAGE_URI}"
docker tag "${ECR_REPO}:latest" "${IMAGE_URI}"
docker push "${IMAGE_URI}"

echo ">> Updating Lambda function ${LAMBDA_NAME}"
aws lambda update-function-code \
  --region "${AWS_REGION}" \
  --function-name "${LAMBDA_NAME}" \
  --image-uri "${IMAGE_URI}" >/dev/null

echo ">> Waiting for update to settle"
aws lambda wait function-updated \
  --region "${AWS_REGION}" \
  --function-name "${LAMBDA_NAME}"

echo ">> Done."
