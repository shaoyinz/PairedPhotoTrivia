# Couples Photo Quiz

A two-player iOS game, in progress. It finds trips a couple took together by matching photo time
and location across both partners' photo libraries, then quizzes each partner on the other's
photos: where and when was this?

**Status:** phase 1, a Python spike that checks trip detection against real libraries. There is no
app yet.

**[Play the demo](https://shaoyinz.github.io/PairedPhotoTrivia/)**: one round with a made-up couple,
in the browser. Source in [`demo/`](demo/).

## How trips are found

- Each phone puts its photos into cells about 1 km wide and 1 hour long (geohash-6 × UTC hour),
  then salts each cell with HMAC-SHA256 using a key only the two paired phones hold.
- The phones compare salted cells. Cells both have, outside each partner's home–work area, are
  hours you were in the same place.
- Matched hours join into a trip once there are at least 5 photos between you. A trip runs across
  nights until one of you is back in your home city.
- No face recognition. Photos, coordinates and timestamps stay on the phone; only salted cells,
  and quiz photos their owner approves, are shared.

Full spec: [`docs/PRD.md`](docs/PRD.md).

## Layout

| Path | What's there |
| --- | --- |
| `docs/` | Product spec |
| `spike/` | Python trip-detection spike: filters, buckets, matching, home/work, trips, evaluation |
| `ios/MetadataExport/` | Throwaway iOS app that exports Photos metadata (never pixels) to CSV |
| `demo/` | Static web demo, deployed to GitHub Pages on push |
| `data/` | Local exports and results; gitignored, never committed |

## Run the spike

Needs [uv](https://docs.astral.sh/uv/); Python 3.12 is pinned.

```bash
cd spike
uv sync
make test                          # unit tests
make skeleton DATA=/tmp/pq-synth   # the whole pipeline on synthetic data
```

## License

Code: [MIT](LICENSE). The demo's photos keep their own Wikimedia Commons licenses; see
[`demo/README.md`](demo/README.md).
