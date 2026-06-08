# syntax=docker/dockerfile:1

# --- build stage: produce a wheel from the source tree ---
FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv
WORKDIR /src
COPY . .
RUN uv build --wheel --out-dir /dist

# --- runtime stage: install just the wheel, run as a non-root user ---
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
USER app

# Default to the streamable-http transport bound on all interfaces so the
# container is reachable; override the CMD for stdio or a different transport.
EXPOSE 8000
ENTRYPOINT ["gopher-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
