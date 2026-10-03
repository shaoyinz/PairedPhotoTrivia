# Walking skeleton (§1.1.7): the whole pipeline on synthetic data, gated on the planted trips.
# Safe over real data: synth and anchors refuse to replace a file the pipeline did not write
# (a real export, hand labels, edited anchors), so the run stops at synth. DATA=<dir> runs it elsewhere.
DATA ?= ../data
PQ := uv run photoquiz

.PHONY: skeleton test
skeleton:
	$(PQ) synth --out $(DATA)
	$(PQ) ingest -p a --data $(DATA)
	$(PQ) ingest -p b --data $(DATA)
	$(PQ) filter -p a --data $(DATA)
	$(PQ) filter -p b --data $(DATA)
	$(PQ) buckets -p a --expand --data $(DATA)
	$(PQ) buckets -p b --raw --data $(DATA)
	$(PQ) match --data $(DATA)
	$(PQ) anchors -p a --data $(DATA)
	$(PQ) anchors -p b --data $(DATA)
	$(PQ) trips --data $(DATA)
	$(PQ) sweep --data $(DATA)
	# all four planted trips found, Tahoe as one (recall 1), and the 4-photo near-trip absent (precision 1)
	$(PQ) report --min-precision 1.0 --min-recall 1.0 --data $(DATA)

test:
	uv run pytest -q
