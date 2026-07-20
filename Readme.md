# Video Processing Platform

A small backend platform for uploading a video, processing it asynchronously (metadata extraction + thumbnail generation), and retrieving its status — built to learn containerized, production-style workloads on AWS.

## Learning Goals

- Amazon ECS + AWS Fargate
- Docker
- Application Load Balancer
- Amazon RDS (PostgreSQL)
- Amazon ECR
- VPC fundamentals (subnets, security groups, NAT)
- Asynchronous processing (S3 → SQS → worker)
- Deploying and operating production-style backend services with infrastructure as code (AWS CDK)

## Features

- **Upload a video** — the client uploads directly to S3 via a presigned URL; video bytes never pass through the API.
- **Asynchronous processing** — an independently scalable worker service extracts metadata (`ffprobe`), generates a thumbnail, and transcodes standard-resolution renditions (`ffmpeg`) for every upload, with retries and idempotent processing.
- **Status retrieval** — poll for processing status, extracted metadata, and presigned download URLs for generated assets.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — networking, security groups, compute, data model, and system flows.
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — local development setup and commands.
