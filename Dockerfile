# syntax=docker/dockerfile:1

# Both stages sit one minor behind the top of the CI test matrix, which now
# covers 3.11-3.14. Do not bump past a version the matrix covers: an
# interpreter the locked dependencies have no wheels for breaks only the
# container, never a test run.
#
# 3.13, not 3.14, on purpose. The 3.14 matrix leg is new and has not yet been
# seen green on GitHub's runners -- only locally, on macOS/arm64. This image
# was already rolled back from python:3.14-slim once (CHANGELOG: "outside the
# tested matrix"), and the whole point of the rule above is that the container
# is the one artifact whose breakage no test run can catch. Bump both FROM
# lines to python:3.14-slim once the `Test Python 3.14 on ubuntu-latest` leg
# has passed on CI; nothing else is blocking it.

# --- build stage: produce a wheel from the source tree ---
FROM python:3.13-slim AS build
RUN pip install --no-cache-dir uv
WORKDIR /src
COPY . .
RUN uv build --wheel --out-dir /dist

# --- runtime stage: install just the wheel, run as a non-root user ---
FROM python:3.13-slim
RUN useradd --create-home --uid 10001 app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

# Pre-create the Gemini state directory, owned by app and mode 700, so that a
# named volume mounted at this path comes up with the right ownership instead
# of root-owned. This directory holds the TOFU certificate pins
# (~/.gemini/tofu.json) and client-certificate private keys (~/.gemini/certs/),
# and TOFU is on by default. Without a mount it dies with the container, so the
# documented `docker run --rm` re-armed blind trust-on-first-use on every start
# -- the CERTIFICATE_CHANGED check is the only thing authenticating a Gemini
# server -- and destroyed any client identity the user minted, whose private
# key is unrecoverable. Run the image as:
#
#   docker run --rm -p 8000:8000 -v gopher-mcp-gemini:/home/app/.gemini gopher-mcp
#
# Deliberately NOT a bare `VOLUME /home/app/.gemini`: an anonymous volume is
# recreated per `docker run` and deleted again by `--rm`, so it would persist
# nothing while making the image look like it does.
RUN install -d -o app -g app -m 700 /home/app/.gemini

USER app

# Default to the streamable-http transport bound on all interfaces so the
# container is reachable; override the CMD for stdio or a different transport.
EXPOSE 8000

# Probe the /health route the HTTP transports serve. Before it existed an
# orchestrator had only `/` (404) and `/mcp` (400 to anything short of a
# session handshake) to read, so a wedged process looked exactly like a healthy
# one and was never restarted or drained from a pool. python:slim ships neither
# curl nor wget, hence the interpreter that is already here.
#
# This assumes the default CMD below: the port is hard-coded to 8000, so
# override the healthcheck alongside --port, and run a stdio container
# (`docker run --no-healthcheck ... --transport stdio`) with the check off --
# stdio serves no HTTP and would otherwise be reported unhealthy while working.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

ENTRYPOINT ["gopher-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
