# SOMER 2.0 Makefile
# ==================
# Common development tasks

VENV_DIR ?= .venv
PYTHON := $(VENV_DIR)/bin/python3
PIP := $(VENV_DIR)/bin/pip

.PHONY: help setup install install-dev test lint format clean run doctor venv

# Default target
help:
	@echo "SOMER 2.0 Development Commands"
	@echo "==============================="
	@echo ""
	@echo "Setup:"
	@echo "  make setup        Create venv + install all dependencies"
	@echo "  make venv         Create virtual environment only"
	@echo "  make install      Install SOMER in development mode"
	@echo "  make install-dev  Install with dev dependencies"
	@echo "  make install-all  Install with all optional dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make test         Run all tests"
	@echo "  make test-v       Run tests with verbose output"
	@echo "  make test-cov     Run tests with coverage"
	@echo "  make test-unit    Unit tests only"
	@echo "  make lint         Run linter (ruff)"
	@echo "  make format       Format code (ruff)"
	@echo "  make typecheck    Run type checker (mypy)"
	@echo "  make check        lint + typecheck + test"
	@echo ""
	@echo "Running:"
	@echo "  make gateway      Start the WebSocket gateway"
	@echo "  make doctor       Check system health"
	@echo "  make onboard      Run setup wizard"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean        Remove build artifacts"
	@echo "  make clean-all    Remove all generated files"

# =============
# Virtual Environment
# =============

venv:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "Creando virtual environment en $(VENV_DIR)..."; \
		python3 -m venv $(VENV_DIR); \
		echo "Virtual environment creado. Actívalo con: source $(VENV_DIR)/bin/activate"; \
	else \
		echo "Virtual environment ya existe en $(VENV_DIR)"; \
	fi

# =============
# Installation (requiere venv activo o usa make setup)
# =============

setup: venv
	$(PIP) install -e ".[all,dev]"
	@echo ""
	@echo "Setup completo. Activa el venv con:"
	@echo "  source $(VENV_DIR)/bin/activate"
	@echo ""
	@echo "Luego ejecuta: somer onboard"

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

install-all:
	pip install -e ".[all,dev]"

# =============
# Testing
# =============

test:
	PYTHONPATH=. python3 -m pytest tests/ --tb=short

test-v:
	PYTHONPATH=. python3 -m pytest tests/ -v --tb=short

test-cov:
	PYTHONPATH=. python3 -m pytest tests/ --cov=agents --cov=providers --cov=channels --cov=gateway --cov=memory --cov=sessions --cov-report=html --cov-report=term

test-unit:
	PYTHONPATH=. python3 -m pytest tests/unit/ -v

test-integration:
	PYTHONPATH=. python3 -m pytest tests/integration/ -v

test-gateway:
	PYTHONPATH=. python3 -m pytest tests/unit/gateway/ -v

test-providers:
	PYTHONPATH=. python3 -m pytest tests/unit/providers/ -v

test-memory:
	PYTHONPATH=. python3 -m pytest tests/unit/memory/ -v

test-sessions:
	PYTHONPATH=. python3 -m pytest tests/unit/sessions/ -v

# =============
# Code Quality
# =============

MODULES = agents channels cli config context_engine gateway hooks infra memory \
          plugins providers secrets security sessions shared skills entry.py

lint:
	python3 -m ruff check $(MODULES)

lint-fix:
	python3 -m ruff check $(MODULES) --fix

format:
	python3 -m ruff format $(MODULES)

typecheck:
	python3 -m mypy $(MODULES) --ignore-missing-imports

check: lint typecheck test
	@echo "All checks passed!"

# =============
# Running
# =============

gateway:
	somer gateway start

doctor:
	somer doctor check

onboard:
	somer onboard

# =============
# Cleanup
# =============

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

clean-all: clean
	rm -rf htmlcov/
	rm -rf .coverage

# =============
# Build
# =============

build:
	pip3 install build
	python3 -m build

publish-test:
	pip install twine
	twine upload --repository testpypi dist/*

publish:
	pip install twine
	twine upload dist/*
