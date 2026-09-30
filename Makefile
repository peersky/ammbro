PY := uv run python

.PHONY: all setup data onchain studies \
        download parse bars extract txs score gate labels \
        study-a study-b study-d study-e supp1 test clean

# Full §17.9 chain: benchmark data -> on-chain swaps -> scoring -> control
# gate -> labels -> studies. `gate` exits non-zero on failure, so no study
# target can run against a pool that failed the calm-period control.
all: data onchain studies

data: download parse bars
onchain: extract txs score gate labels
studies: study-a study-b supp1 study-d study-e

setup:
	uv venv && uv pip install -e ".[dev]"

# --- Layer 2/3 benchmark (Binance public archive) ---
download:
	$(PY) -m pipeline.binance_download

parse:
	$(PY) -m pipeline.binance_parse

bars:
	$(PY) -m pipeline.benchmark

# --- On-chain extraction + scoring ---
extract:
	$(PY) -m pipeline.extract_swaps

txs:
	$(PY) -m pipeline.extract_txs

score:
	$(PY) -m pipeline.qlp

gate:
	$(PY) -m pipeline.control_gate

labels:
	$(PY) -m pipeline.labels

# --- Studies (§17.1) ---
study-a:
	$(PY) -m pipeline.study_a

study-b:
	$(PY) -m pipeline.study_b

supp1:
	$(PY) -m pipeline.supp1

study-d:
	$(PY) -m pipeline.study_d

study-e:
	$(PY) -m pipeline.study_e

test:
	$(PY) -m pytest -q

clean:
	rm -rf data/parquet data/bars
