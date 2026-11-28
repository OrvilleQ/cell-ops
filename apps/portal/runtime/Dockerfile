FROM python:3.15.2-slim-bookworm@sha256:498829c717b1e59fc42f0e7865eafe4e04ca0f70a3769d4ae70ba218df54507c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/requirements.txt && rm /tmp/requirements.txt
WORKDIR /app
COPY assets/ /opt/portal-assets/
USER 1000:1000
EXPOSE 8080
CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=1", "--worker-class=gthread", "--threads=4", "--worker-connections=32", "--backlog=32", "--timeout=30", "--graceful-timeout=15", "--keep-alive=2", "--limit-request-line=2048", "--limit-request-fields=24", "--limit-request-field_size=4096", "--worker-tmp-dir=/tmp", "portal:create_app()"]
