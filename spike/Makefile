# Walking skeleton (§1.1.7). Fails at the first NotImplementedError until §1.3–1.8 land;
# that failure moving down the pipeline is the progress metric.
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
	$(PQ) anchors -p a --force --data $(DATA)
	$(PQ) anchors -p b --force --data $(DATA)
	$(PQ) trips --data $(DATA)
	# all four planted trips found, Tahoe as one (recall 1), and the 4-photo near-trip absent (precision 1)
	$(PQ) report --min-precision 1.0 --min-recall 1.0 --data $(DATA)

test:
	uv run pytest -q
