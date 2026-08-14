# Makefile do quantlab.
#
# `make check` é o portão local e roda exatamente os mesmos alvos que o job
# "quality" do CI (.github/workflows/ci.yml) invoca: lint, typecheck, test.
# Se divergirem, o CI é a fonte da verdade e este arquivo está errado.

SHELL := /bin/bash

UV      ?= uv
RUN     := $(UV) run
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

.PHONY: help up down logs install test test-unit test-integration \
        lint format typecheck audit check rnf04 clean

help: ## Lista os alvos disponíveis
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ─── Ambiente ────────────────────────────────────────────────────────────────

up: ## Sobe o MongoDB e espera o healthcheck passar
	$(COMPOSE) up -d --wait

down: ## Derruba os containers, preservando o volume de dados
	$(COMPOSE) down

logs: ## Acompanha os logs dos containers
	$(COMPOSE) logs -f

install: ## Instala dependências de runtime e de desenvolvimento
	$(UV) sync --all-groups

# ─── Testes ──────────────────────────────────────────────────────────────────

test: ## Suíte default (integração desmarcada) com cobertura — o que o CI roda
	$(RUN) pytest --cov --cov-report=term-missing --cov-report=xml

test-unit: ## Apenas os testes marcados como unit
	$(RUN) pytest -m unit

test-integration: ## Apenas os testes marcados como integration (exige `make up`)
	@# Sem tolerância a exit 5 (nada coletado): o Bloco A trouxe testes de
	@# integração, e a partir daqui "nenhum teste coletado" é uma falha de
	@# verdade — significa que a suíte sumiu, não que ela não existe.
	$(RUN) pytest -m integration

# ─── Qualidade ───────────────────────────────────────────────────────────────

lint: ## ruff check + verificação de formatação
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Aplica formatação e correções automáticas do ruff
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck: ## mypy --strict (RNF-05)
	$(RUN) mypy src tests

audit: ## Vulnerabilidades conhecidas nas dependências instaladas
	@# --skip-editable pula o próprio quantlab, que não está publicado no PyPI.
	$(RUN) pip-audit --skip-editable

check: lint typecheck test ## Portão local completo — espelha o job "quality" do CI

rnf04: ## Harness do RNF-04 — mede o cômputo (20 ativos x 10 anos < 30 s; escopo declarado em scripts/rnf04_harness.py)
	$(RUN) python scripts/rnf04_harness.py

# ─── Limpeza ─────────────────────────────────────────────────────────────────

clean: ## Remove caches, artefatos de build e relatórios de cobertura
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist build
	rm -f .coverage .coverage.* coverage.xml
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
