# syntax=docker/dockerfile:1
# Defenestrator: the scheduler plus the official Claude Code and Codex CLIs (it pings with
# them, never with an API key). Bump the pinned CLI versions by hand.
FROM node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da

ARG CLAUDE_VERSION=2.1.306
ARG CODEX_VERSION=0.157.1
# Match the host user that owns the mounted ~/.claude and ~/.codex (the files are mode 600).
ARG UID=1000
ARG GID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 curl ca-certificates tini tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force
RUN userdel node && rm -rf /home/node \
    && groupadd -g "${GID}" app \
    && useradd -m -u "${UID}" -g "${GID}" app \
    && mkdir /state && chown app:app /state

USER app
ENV PATH="/home/app/.local/bin:${PATH}"
RUN curl -fsSL https://claude.ai/install.sh | bash -s -- "${CLAUDE_VERSION}" \
    && claude --version

WORKDIR /app
COPY --chown=app:app src ./src
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    DEFENESTRATOR_STATE=/state
VOLUME /state

HEALTHCHECK --interval=5m --timeout=10s --start-period=2m --retries=2 \
    CMD ["python3", "-m", "defenestrator", "health"]
ENTRYPOINT ["tini", "--", "python3", "-m", "defenestrator"]
CMD ["run"]
