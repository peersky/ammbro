PY := uv run python

.PHONY: all setup data onchain studies \
        download parse bars extract txs score gate labels \
        study-a study-b study-d study-e study-g study-h study-j sim-inputs study-i supp1 figures test clean \
        paper-results settlement paper-pdf preprint paper-rendered

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

# Study I runs behind paper §5 and Appendix F, on both chains (needs sim-inputs for each chain)
PAPER_RUNS := study_i_headline study_i_index study_i_paths study_i_redundancy study_i_stake study_i_relief \
              study_i_review study_i_bonus study_i_rotation study_i_final
paper-results:
	for c in mainnet arbitrum; do for m in $(PAPER_RUNS); do AMMBRO_CHAIN=$$c $(PY) -m pipeline.$$m || exit 1; done; done
	AMMBRO_CHAIN=mainnet $(PY) -m pipeline.study_i_position
	AMMBRO_CHAIN=arbitrum $(PY) -m pipeline.study_i_timeboost

settlement:              # Study C (collateral) and K1–K4 (keepers, gas tank)
	$(PY) -m pipeline.study_c_collateral
	for m in study_k study_k2 study_k3 study_k4; do $(PY) -m pipeline.$$m || exit 1; done

figures:                 # paper figures from committed results
	$(PY) -m pipeline.figures

test:
	$(PY) -m pytest -q

clean:
	rm -rf data/parquet data/bars

paper-pdf: # render paper.md (LaTeX math) to paper.pdf via pandoc + xelatex
	uv run python tools/mermaid2png.py
	pandoc paper.md -o paper.pdf --pdf-engine=xelatex -V mainfont="Times New Roman" -V geometry:margin=2.2cm -V fontsize=10pt --resource-path=. --lua-filter=tools/math-block.lua --citeproc --bibliography=references.bib

preprint:                # preprint PDF for Zenodo → dist/bro-amm-preprint.pdf (vector figures, .bib citations)
	uv run python tools/mermaid2png.py
	AMMBRO_FIG=pdf uv run python -m pipeline.figures
	pandoc paper.md -o dist/bro-amm-preprint.pdf --pdf-engine=xelatex --resource-path=. \
	  --metadata-file=tools/preprint.yaml --lua-filter=tools/math-block.lua --lua-filter=tools/preprint.lua --citeproc

paper-rendered:          # paper.rendered.md: paper.md with citations and references filled in, for Forgejo
	uv run python tools/render_md.py
