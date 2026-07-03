# Makefile — unified dev/ops entry point for tincan-iris.
#
# NFR1: `install`/`lint`/`test`/`verify` below must stay byte-for-byte
# identical to .github/workflows/ci.yml's steps. If you edit one, edit both.

.DEFAULT_GOAL := help

.PHONY: help install lint test verify \
	daemon daemon-stop daemon-status daemon-callcard \
	console callcard whisper stt kokoro tts \
	services doctor tincan-status up run

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*##"}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Install the package + console/call-card extras + dev tools
	pip install -e '.[console,call-card]' pytest ruff

lint: ## Lint with ruff
	ruff check .

test: ## Run the test suite
	pytest -q

verify: lint test ## Lint then test, same order as CI

daemon: ## Start the iris daemon (backgrounded; safe to re-run)
	iris daemon start

daemon-stop: ## Stop the iris daemon
	iris daemon stop

daemon-status: ## Show iris daemon status
	iris daemon status

daemon-callcard: ## Start the daemon with Call Card capture forced on
	IRIS_CALL_CARD=1 iris daemon start

console: ## Launch the operator console (Textual TUI)
	iris console

callcard: ## Call Card standalone view — stub, not wired yet (see ti-913rw)
	@echo "make callcard: not wired yet — see ti-913rw" >&2; exit 1

# stt/tts/run are undocumented aliases for whisper/kokoro/up — no ## comment
# on purpose, so `make help` shows one canonical name per command (ADR-2).
whisper: ## Run the whisper STT server (alias: stt)
	iris whisper-server

stt:
	iris whisper-server

kokoro: ## Run the kokoro TTS server (alias: tts)
	iris kokoro-server

tts:
	iris kokoro-server

services: ## Install/refresh the systemd user services
	iris install-services

doctor: ## Health-check assets + services
	iris doctor

tincan-status: ## Deep tincand check (D-Bus/SELinux/adapter)
	iris doctor --check tincand

up: ## Bring the stack up and launch the console (alias: run)
	iris up

run:
	iris up
