# syntax=docker/dockerfile:1
#
# Imagem da aplicação quantlab.
#
# Ainda não entra no docker-compose.yml: na Fase 0 o CLI roda no host e o
# compose sobe apenas o banco. A imagem existe para que o empacotamento seja
# um problema já resolvido quando a Fase 5 (infra) chegar.

# ─── builder ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependências primeiro: a camada só invalida quando o lock muda.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Depois o código do projeto.
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ─── runtime ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Usuário não-root: o processo nunca precisa de privilégio.
RUN groupadd --gid 1000 quantlab \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin quantlab

WORKDIR /app

COPY --from=builder --chown=quantlab:quantlab /app/.venv /app/.venv
COPY --from=builder --chown=quantlab:quantlab /app/src /app/src
COPY --chown=quantlab:quantlab config/ /app/config/

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QUANTLAB_ENV=prod

USER quantlab

ENTRYPOINT ["python", "-m", "quantlab"]
CMD ["version"]
