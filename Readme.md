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
- [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) — local development setup and commands, including full load-test numbers.

## Estimated scale

### Would this architecture handle 100k DAU?

Yes -- reachable by pure horizontal scaling of the exact same design (more Fargate worker tasks, a bigger RDS instance), no redesign. But the required fleet size swings hugely depending on real upload frequency, since 1 vs 7 videos/week/user is a 7x difference in total load:

| Assumption | Videos/day (100k DAU) | Worker tasks needed (`cpu=2048`, concurrency 4 each, ~3,750 videos/day/task) | RDS | Estimated monthly AWS cost |
|---|---|---|---|---|
| 1 video/user/week (low end) | ~14,300 | ~4 tasks | `db.t4g.small`/`medium` | ~$440/mo |
| 4 videos/user/week (midpoint) | ~57,100 | ~15 tasks | `db.t4g.large` | ~$1,300/mo |
| 7 videos/user/week (high end) | ~100,000 | ~27 tasks | `db.t4g.large`/`xlarge` | ~$2,300/mo |

The API side stays comfortably ahead throughout (100k DAU polling occasionally is far lighter than 27 worker tasks' combined DB load) -- 2-4 API tasks is plenty at every point in this range. The worker fleet size is the real number to get right, and it's worth measuring actual upload frequency before committing to a task count anywhere in that 4-27 range.

Cost figures are rough, on-demand list-price estimates (Fargate ~$0.04048/vCPU-hr + ~$0.004445/GB-hr, RDS single-AZ Postgres, ~730 hrs/month), including a roughly constant ~$60/month baseline for the ALB + NAT gateway shared across all tiers. Excludes data transfer, S3/SQS/CloudWatch (small at this scale), and any Reserved/Savings Plan discounts, which commonly cut 30-50% off these numbers for steady-state workloads.
