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
        lint format typecheck audit check clean

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
	@# pytest devolve 5 quando não coleta nada. Na Fase 0 ainda não existe
	@# teste de integração, e um alvo vermelho por ausência seria ruído.
	@# Remover esta tolerância assim que o primeiro teste de integração entrar.
	@$(RUN) pytest -m integration; status=$$?; \
		if [ $$status -eq 5 ]; then \
			echo "Nenhum teste de integração ainda (Fase 0)."; exit 0; \
		fi; \
		exit $$status

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

# ─── Limpeza ─────────────────────────────────────────────────────────────────

clean: ## Remove caches, artefatos de build e relatórios de cobertura
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist build
	rm -f .coverage .coverage.* coverage.xml
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
