FROM python:3.11-slim

# One BLAS / OpenMP thread: the server is a single process, and its costly endpoints are capped
# in the app (backend/limits.py), so each request should use one core rather than all of them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

WORKDIR /opt/tdss

# pypdf lets the prediction model read PDF documents; uploaded PDFs are untrusted input, so the
# floor is the release with the latest fixes for malformed-file DoS advisories (GHSA, Oct 2026).
# The Anthropic SDK is only needed for the optional LLM extractor (TDSS_LLM_EXTRACTION=1), so it
# is opt-in: --build-arg WITH_LLM=1.
ARG WITH_LLM=0
COPY requirements.txt .
RUN pip install -r requirements.txt "pypdf>=6.21.4" \
    && if [ "$WITH_LLM" = "1" ]; then pip install "anthropic>=2.0"; fi

COPY app/ app/
COPY backend/ backend/
COPY assets/ assets/
COPY corpus/ corpus/
# The shipped corpus doubles as the seed for an empty documents volume (docker-entrypoint.sh).
RUN cp -r corpus/documents corpus/seed \
    && mkdir -p .cache/gis \
    && chmod +x backend/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/contexts', timeout=4)"

ENTRYPOINT ["backend/docker-entrypoint.sh"]
# One worker: the trained model and the corpus lock live in this process (CorpusStore).
# --proxy-headers trusts X-Forwarded-For only from FORWARDED_ALLOW_IPS (default 127.0.0.1;
# docker-compose.zima.yml sets nginx's network). Past 64 open connections uvicorn answers 503.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--limit-concurrency", "64"]
