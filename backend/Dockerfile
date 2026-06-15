FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev curl git \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Create data directories
RUN mkdir -p data/chroma_db data/raw_docs data/processed \
             data/synthetic/generators app/ai/anomaly/models

# Download embedding model at build time (avoids cold start delay)
RUN python -c "from sentence_transformers import SentenceTransformer; \
               SentenceTransformer('nomic-ai/nomic-embed-text-v1.5', trust_remote_code=True)" || true

# Download reranker model
RUN python -c "from sentence_transformers import CrossEncoder; \
               CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512)" || true

EXPOSE 10000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
