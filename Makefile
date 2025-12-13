.PHONY: help lint test build clean

PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

help:
	@echo "ZenithAlgo Make Targets"
	@echo "  make lint   - markdownlint (requires markdownlint-cli)"
	@echo "  make test   - run pytest (skip live by default)"
	@echo "  make build  - placeholder"
	@echo "  make clean  - placeholder"

lint:
	@command -v markdownlint >/dev/null 2>&1 || { \
		echo "markdownlint not found. Install: npm install -g markdownlint-cli"; \
		exit 1; \
	}
	@markdownlint -c .markdownlint.json --ignore-path .markdownlintignore "**/*.md"

test:
	@$(PYTHON) -m pytest -q -m "not live"

build:
	@echo "build: placeholder (no build pipeline configured yet)"

clean:
	@echo "clean: placeholder (no artifacts cleanup configured yet)"
