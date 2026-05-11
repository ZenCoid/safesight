#!/usr/bin/env bash
set -euo pipefail

echo "============================================"
echo " SafeSight Infrastructure Bootstrap"
echo "============================================"

# Create local volume directories if they don't exist
mkdir -p ./data/postgres
mkdir -p ./data/redis
mkdir -p ./data/minio

echo "📁 Local data directories created/verified."

# Ensure .env exists with placeholder if not
if [ ! -f .env ]; then
    echo "DATABASE_URL=postgresql+asyncpg://safesight:safesight_pass@localhost:5432/safesight_db" > .env
    echo "REDIS_URL=redis://localhost:6379/0" >> .env
    echo "MINIO_ENDPOINT=localhost:9000" >> .env
    echo "MINIO_ACCESS_KEY=minioadmin" >> .env
    echo "MINIO_SECRET_KEY=minioadmin" >> .env
    echo "MINIO_BUCKET=safesight-clips" >> .env
    echo "RFDETR_MODEL_PATH=models/rfdetr_base.pth" >> .env
    echo "TEACHER_MODEL_PATH=models/teacher_best.pt" >> .env
    echo "LOW_CONFIDENCE_THRESHOLD=0.3" >> .env
    echo "PSEUDO_LABEL_BATCH_SIZE=32" >> .env
    echo "📝 Created default .env file."
fi

# Launch the stack
docker-compose up -d

echo ""
echo "✅ Infrastructure is starting:"
echo "   - PostgreSQL + TimescaleDB on :5432"
echo "   - Redis on :6379"
echo "   - MinIO S3 on :9000  (console on :9001)"
echo ""
echo "All data is persisted in ./data/"
echo "Use 'docker-compose down' to stop services without deleting volumes."
echo ""