.PHONY: help setup gui lint test ingest simulate score ic leakage-audit backtest cpcv discover dossier extract propose submit report research-export tax-review journal reproduce clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup:   ## Install dependencies
	uv sync || pip install -r requirements.txt

gui:     ## Launch the browser-based GUI (wraps every command below)
	uv run streamlit run src/durable/gui/app.py || streamlit run src/durable/gui/app.py

lint:    ## Ruff check + format
	ruff check src tests && ruff format --check src tests

test:    ## Run test suite
	pytest -q --cov=src/durable --cov-report=term-missing

ingest:  ## Refresh all raw data into DuckDB
	python -m durable.data.ingest --all

simulate: ## End-to-end dry run on synthetic data; asserts PROTOCOL 4.1 invariants
	python -m durable.backtest.engine --simulate --assert-invariants

leakage-audit: ## Firewall sweep: future-dated rows, lag violations, adjusted prices
	python -m durable.data.firewall --audit

score:   ## Factor scores for a date (make score AS_OF=2026-08-21)
	python -m durable.portfolio.rank --as-of $(AS_OF)

ic:      ## Information coefficient + decay for a factor (make ic FACTOR=durability)
	python -m durable.factors.ic --factor $(FACTOR)

backtest: ## Walk-forward backtest (make backtest SEGMENT=design)
	python -m durable.backtest.engine --segment $(SEGMENT)

cpcv:    ## Combinatorial purged CV -> PBO (docs/09)
	python -m durable.backtest.cpcv --n-groups 10 --k 3

discover: ## Sleeve E screens -> watchlist (no orders)
	python -m durable.discovery.screens --as-of $(AS_OF)

dossier: ## Discovery Dossier for one ticker (make dossier TICKER=XYZ)
	python -m durable.discovery.dossier --ticker $(TICKER)

extract: ## LLM filing extraction (make extract TICKER=XYZ)
	python -m durable.signals.extract --ticker $(TICKER)

propose: ## Order proposal. Sends nothing.
	python -m durable.execution.propose --as-of $(AS_OF)

submit:  ## Submit a reviewed proposal. Human-gated; a hook blocks agent invocation.
	@echo "Run manually: python -m durable.execution.submit --proposal <file> --i-have-read-the-proposal"

report:  ## Performance report (make report TYPE=pulse|quarterly|research|event|annual)
	python -m durable.reporting.report --type $(or $(TYPE),quarterly)

research-export: ## Research bulletin: JSON, CSV, LaTeX, 300dpi figures
	python -m durable.reporting.report --type research --export

tax-review: ## Lots, harvest candidates, wash-sale check, tax alpha
	python -m durable.tax.harvest --review

journal: ## Decision journal + calibration scoring
	python -m durable.research.calibration --score

reproduce: ## Regenerate a prior report byte-identically (make reproduce COMMIT=abc123)
	python -m durable.research.preregister --reproduce $(COMMIT)

clean:
	rm -rf .pytest_cache __pycache__ .coverage
