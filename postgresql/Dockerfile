FROM postgres:16.15-bookworm@sha256:1938c16e9d2f10a6a3623b344b64ae8d45f407f2c5f34f0979468bb689b9227a
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-psycopg2 age ca-certificates && rm -rf /var/lib/apt/lists/*
COPY scripts/ /opt/platform/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/opt/platform/platform.py"]
