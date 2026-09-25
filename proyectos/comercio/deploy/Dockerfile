FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLCONFIGDIR=/tmp/matplotlib BRAIN_REGISTRY=/models BRAIN_MODE=production BRAIN_PROJECT_ROOT=/app
COPY pyproject.toml README.md ./
COPY config/requirements.lock config/requirements.lock
COPY src/ src/
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home brain
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=3)"
CMD ["python", "-m", "uvicorn", "decision_brain.service:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "32", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "20", "--no-access-log"]
