PY := uv run python

.PHONY: all setup data onchain studies \
        download parse bars extract txs score gate labels \
        study-a study-b study-d study-e study-g study-h study-j sim-inputs study-i supp1 test clean

# Full §17.9 chain: benchmark data -> on-chain swaps -> prepare -> labels
# -> Study E (measures L, writes canonical q for both pools) -> control
# gate -> studies. `gate` exits non-zero on failure, so no study target can
# run against a pool that failed the calm-period control.
all: data onchain studies

data: download parse bars
onchain: extract txs score labels
studies: study-a study-b supp1 study-d study-h study-i

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

gate: study-e
	$(PY) -m pipeline.control_gate

labels:
	$(PY) -m pipeline.labels

# --- Studies (§17.1) ---
study-a: gate
	$(PY) -m pipeline.study_a

study-b: gate
	$(PY) -m pipeline.study_b

supp1: gate
	$(PY) -m pipeline.supp1

study-d: gate
	$(PY) -m pipeline.study_d

study-e:
	$(PY) -m pipeline.study_e

study-g:                 # RPC (receipts, traces) + Foundry (contracts/)
	$(PY) -m pipeline.study_g

study-j: gate
	$(PY) -m pipeline.study_j

study-h: gate
	$(PY) -m pipeline.study_h

sim-inputs: gate
	$(PY) -m pipeline.blocksim

study-i: sim-inputs
	$(PY) -m pipeline.study_i

test:
	$(PY) -m pytest -q

clean:
	rm -rf data/parquet data/bars
