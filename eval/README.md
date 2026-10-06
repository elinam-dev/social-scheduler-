# Clip quality evaluation set

`manifest.json` contains 20 video placeholders. Add your own rights-cleared
videos under `eval/videos/` and annotate one or more human-selected good clips
for each video by filling its `clips` array:

```json
{
  "id": "video-01",
  "path": "videos/video-01.mp4",
  "clips": [
    {
      "start_seconds": 42.5,
      "end_seconds": 78.0,
      "title": "Optional reference title",
      "notes": "Optional reason this is a strong, self-contained clip"
    }
  ]
}
```

Clip times are seconds from the beginning of the source video. The manifest
schema is in `manifest.schema.json`. Video files are excluded from Git; do not
commit source videos or other media. Evaluation requires locally available
videos and at least one hand-labeled clip per video.

## Evaluating candidate scores

Record the worker's candidate boundaries and normalized signal scores in
`predictions.json`, following `predictions.schema.json`. Use the same video IDs
as the manifest. The evaluator ranks and deduplicates candidates per video,
then reports recall@N against labeled clips using temporal intersection-over-
union (IoU). It searches linear score weights in increments of 0.1 by default
and includes the current production weights as a baseline:

```sh
python -m eval.evaluate --manifest eval/manifest.json \
  --predictions eval/predictions.json --top-n 5 --min-iou 0.5
```

Tune against completed annotations only; empty placeholders are ignored. The
evaluation output is diagnostic and does not change runtime weights by itself.
