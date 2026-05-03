# workout-log

A small FastAPI service for personal workout logging — strength sets and cardio runs — backed by S3 and runnable on AWS Lambda free tier via a container image in ECR.

## Endpoints

All endpoints except `/healthz` require an `X-API-Key` header matching the `API_KEY` env var.

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Liveness check, no auth |
| `POST` | `/workouts` | Log a new workout |
| `GET` | `/workouts` | List workouts (filters: `date`, `start`, `end`, `exercise`) |
| `GET` | `/workouts/{id}` | Fetch a single workout |
| `DELETE` | `/workouts/{id}` | Delete a workout |
| `GET` | `/stats/weekly?week_of=YYYY-MM-DD` | Totals for the ISO week containing `week_of` (defaults to today) |
| `GET` | `/stats/monthly?month=YYYY-MM` | Totals for the given month (defaults to current) |

### Examples

Log a strength workout:
```bash
curl -X POST localhost:8000/workouts \
  -H 'X-API-Key: dev' -H 'content-type: application/json' \
  -d '{
        "date": "2026-05-03",
        "exercises": [
          {"name": "bench press", "sets": [{"reps": 5, "weight_kg": 80}, {"reps": 5, "weight_kg": 80}]}
        ]
      }'
```

Log a run:
```bash
curl -X POST localhost:8000/workouts \
  -H 'X-API-Key: dev' -H 'content-type: application/json' \
  -d '{
        "date": "2026-05-03",
        "exercises": [
          {"name": "morning run", "distance_km": 5.0, "duration_seconds": 1500}
        ]
      }'
```

History of a specific exercise:
```bash
curl 'localhost:8000/workouts?exercise=bench' -H 'X-API-Key: dev'
```

Workouts on a date / in a range:
```bash
curl 'localhost:8000/workouts?date=2026-05-03' -H 'X-API-Key: dev'
curl 'localhost:8000/workouts?start=2026-05-01&end=2026-05-31' -H 'X-API-Key: dev'
```

Stats:
```bash
curl 'localhost:8000/stats/weekly'  -H 'X-API-Key: dev'
curl 'localhost:8000/stats/monthly?month=2026-05' -H 'X-API-Key: dev'
```

Interactive docs at `http://localhost:8000/docs`.

## Data model

Each workout has a `date`, a list of `exercises`, and optional `notes`. Each exercise carries a `name` plus either:
- `sets`: a list of `{reps, weight_kg}` (strength), or
- `distance_km` and/or `duration_seconds` (cardio).

Validation rejects an exercise that has neither.

## Local development

### With Docker (recommended)

```bash
docker compose up --build
```

Uses the local-filesystem backend. Data persists under `./.data`. API key is `dev`.

### Without Docker

```bash
python -m venv .venv && source .venv/bin/activate    # or .venv/Scripts/activate on Windows
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests cover both the local and the S3 backends (S3 via [`moto`](https://github.com/getmoto/moto)).

## Configuration

| Env var | Required | Default | Notes |
|---|---|---|---|
| `STORAGE_BACKEND` | no | `local` | `local` or `s3` |
| `API_KEY` | required for `s3` | `dev` | Sent as `X-API-Key` header |
| `S3_BUCKET` | required for `s3` | — | Bucket name |
| `AWS_REGION` | no | — | Used by boto3 |
| `LOCAL_DATA_DIR` | no | `./.data` | Only used for local backend |

## AWS deploy (free tier)

The flow is: build image → push to ECR → Lambda runs the container → it reads/writes a single S3 bucket. A Lambda Function URL exposes it over HTTPS.

### One-time setup

Replace `YOUR_SUFFIX` (S3 bucket names are global) and pick a region.

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_REPO=workout-log
export LAMBDA_NAME=workout-log
export S3_BUCKET=workout-log-YOUR_SUFFIX
export API_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(24))')
echo "API_KEY=${API_KEY}   # save this somewhere safe"
```

1. **S3 bucket** for workout JSON:
   ```bash
   aws s3api create-bucket --bucket "$S3_BUCKET" --region "$AWS_REGION" \
     $( [ "$AWS_REGION" = "us-east-1" ] || echo --create-bucket-configuration LocationConstraint=$AWS_REGION )
   aws s3api put-public-access-block --bucket "$S3_BUCKET" \
     --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
   ```

2. **ECR repo** for the image:
   ```bash
   aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION"
   ```

3. **IAM role** for the Lambda — basic execution + read/write on the bucket:
   ```bash
   cat > /tmp/trust.json <<'EOF'
   {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}
   EOF
   aws iam create-role --role-name workout-log-lambda-role --assume-role-policy-document file:///tmp/trust.json
   aws iam attach-role-policy --role-name workout-log-lambda-role \
     --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

   cat > /tmp/s3.json <<EOF
   {"Version":"2012-10-17","Statement":[
     {"Effect":"Allow","Action":["s3:PutObject","s3:GetObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::${S3_BUCKET}/*"},
     {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::${S3_BUCKET}"}
   ]}
   EOF
   aws iam put-role-policy --role-name workout-log-lambda-role \
     --policy-name workout-log-s3 --policy-document file:///tmp/s3.json
   ```

4. **First image push** — same as `infra/deploy.sh` but the function doesn't exist yet:
   ```bash
   aws ecr get-login-password --region "$AWS_REGION" \
     | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
   docker build --platform linux/amd64 -t "$ECR_REPO:latest" .
   docker tag "$ECR_REPO:latest" "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:latest"
   docker push "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:latest"
   ```

5. **Create the Lambda function** from the image:
   ```bash
   aws lambda create-function \
     --function-name "$LAMBDA_NAME" --region "$AWS_REGION" \
     --package-type Image \
     --code ImageUri="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:latest" \
     --role "arn:aws:iam::${AWS_ACCOUNT_ID}:role/workout-log-lambda-role" \
     --timeout 15 --memory-size 512 \
     --environment "Variables={STORAGE_BACKEND=s3,S3_BUCKET=${S3_BUCKET},API_KEY=${API_KEY}}"
   ```

6. **Add a Function URL**:
   ```bash
   aws lambda create-function-url-config \
     --function-name "$LAMBDA_NAME" --region "$AWS_REGION" \
     --auth-type NONE \
     --cors '{"AllowOrigins":["*"],"AllowMethods":["*"],"AllowHeaders":["*"]}'
   aws lambda add-permission \
     --function-name "$LAMBDA_NAME" --region "$AWS_REGION" \
     --statement-id FunctionURLAllowPublicAccess \
     --action lambda:InvokeFunctionUrl \
     --principal '*' --function-url-auth-type NONE
   ```
   The `FunctionUrl` from step 6's output is your endpoint. Auth is enforced at the application layer via `X-API-Key`.

### Subsequent deploys

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=...
export ECR_REPO=workout-log
export LAMBDA_NAME=workout-log
./infra/deploy.sh
```

Smoke check after deploy:
```bash
curl "$FUNCTION_URL/healthz"
curl -H "X-API-Key: $API_KEY" "$FUNCTION_URL/workouts"
```

## Cost note

This stays inside the AWS Always Free / 12-month free tier for personal use:
- Lambda: 1M requests / 400k GB-seconds per month free.
- ECR: 500 MB private storage free for 12 months — one image fits.
- S3: 5 GB / 20k GET / 2k PUT per month free for 12 months — far above personal logging volume.

The main thing that *could* push you out of free tier is `GET /workouts` and stats calls listing the bucket — each call is one `ListObjectsV2` plus one `GetObject` per workout. At one workout/day for a year, that's ~365 GETs per stats call; budget accordingly if you wire up a frontend that polls.
