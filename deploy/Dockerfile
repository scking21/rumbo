# Pin reviewed image digests in the authorized deployment environment before release.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
COPY requirements-owner.txt requirements-authkit.txt ./
RUN python -m pip install --no-cache-dir -r requirements-authkit.txt
COPY pyproject.toml README.md LICENSE ./
COPY rumbo ./rumbo
RUN python -m pip install --no-cache-dir --no-deps .
COPY deploy/entrypoint.py deploy/healthcheck.py ./deploy/
USER 10001:10001
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "/app/deploy/healthcheck.py"]
ENTRYPOINT ["python", "/app/deploy/entrypoint.py"]
