#!/bin/sh
set -eu

awslocal s3api create-bucket \
  --bucket "$S3_BUCKET_NAME" \
  --region "$AWS_DEFAULT_REGION" \
  --create-bucket-configuration "LocationConstraint=$AWS_DEFAULT_REGION"
