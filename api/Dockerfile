FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    openssh-client \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir ansible-core

COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY Ansible ./Ansible
COPY api ./api
COPY id_ed25519 ./id_ed25519

EXPOSE 8000

# --app-dir puts /app/api on sys.path so "app.main" resolves to
# /app/api/app/main.py. Without it uvicorn looks for /app/app/main.py.
CMD ["uvicorn", "app.main:app", "--reload", "--app-dir", "api", "--host", "0.0.0.0", "--port", "8000"]
