FROM python:3.12-slim

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_EXTRA_INDEX_URL=https://pypi.org/simple

COPY datadog-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    --index-url "$PIP_INDEX_URL" \
    --extra-index-url "$PIP_EXTRA_INDEX_URL"

COPY shared/xtap_identity.py /app/xtap_identity.py
COPY datadog-agent/ .

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
