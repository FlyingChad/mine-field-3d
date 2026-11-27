# Mine Field 3D server. Build with `docker compose up -d --build` (see DOCKER.md).
FROM python:3.11-slim

# WITH_AI=1 (default) installs CPU-only PyTorch for the AI lab and the bots (adds about 700 MB).
# WITH_AI=0 makes a small image: the game works, but there are no bots and no lab.
ARG WITH_AI=1

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MF3D_DATA=/app/data

WORKDIR /app

# dependencies first, so an update that only changes the code reuses this layer and rebuilds in seconds
COPY requirements.txt ./
RUN pip install -r requirements.txt \
 && if [ "$WITH_AI" = "1" ]; then \
      pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install numpy; \
    fi

COPY . .
# the starter models are kept aside: /app/models is a volume, and the entrypoint copies in any that are missing
RUN mkdir -p /app/starter-models && cp models/*.pt /app/starter-models/ 2>/dev/null || true \
 && sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-u", "server.py", "--host", "0.0.0.0", "--port", "8080"]
