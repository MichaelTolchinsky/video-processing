#!/bin/sh
set -eu

# Create the queue and wire the bucket's ObjectCreated events to it, so
# local development matches the production PlatformStack wiring
# (SqsDestination + "uploads/" prefix filter).
QUEUE_URL=$(awslocal sqs create-queue \
  --queue-name "$SQS_QUEUE_NAME" \
  --region "$AWS_DEFAULT_REGION" \
  --query QueueUrl --output text)

QUEUE_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names QueueArn \
  --query Attributes.QueueArn --output text)

awslocal s3api put-bucket-notification-configuration \
  --bucket "$S3_BUCKET_NAME" \
  --notification-configuration '{
    "QueueConfigurations": [
      {
        "QueueArn": "'"$QUEUE_ARN"'",
        "Events": ["s3:ObjectCreated:*"],
        "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "uploads/"}]}}
      }
    ]
  }'
