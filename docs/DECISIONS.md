# Decisions

- Stage 0 Compose ports bind to `127.0.0.1` by default. `.env.example` contains
  development-only credentials; replace them before exposing services to a network.
- The MinIO image uses a pinned `bitnamilegacy` release because the official image
  could not be pulled anonymously from Docker Hub or Quay during setup. This archived
  image starts successfully, but its base image may not receive future security
  updates; replace it with a maintained MinIO image source before production use.
- The API container applies Alembic migrations before serving requests; the worker
  shares the API model package so both services use the same persisted schema.
- Initial multi-signal ranking weights are 70% LLM review, 10% normalized audio
  energy, 15% speech-rate fit, and 5% transcript laughter markers. Speech rate
  peaks at 160 words per minute and declines linearly to zero at 40 or 280 WPM;
  audio energy maps -60 to -10 dBFS onto 0 to 1. These heuristics are starting
  values for evaluation and tuning in step 27, not a claim of universal clip quality.
- Speaker-to-face matching uses temporal co-occurrence between diarization turns
  and sampled face detections, with greedy one-to-one speaker/track assignment.
  It does not analyze lip motion and cannot identify the active speaker reliably
  when multiple people remain visible; the result is a reviewable heuristic.
- Step 56 uses the saved clip title as an optional first-2.5-second hook overlay.
  B-roll insertion is deferred because the project has no rights-cleared B-roll
  asset model or selection UI; it must not source footage implicitly.
- Step 57 does not add scheduled publishing. No target social platform has been
  selected, and publishing requires platform-specific OAuth, account consent,
  and API/policy integration beyond local clip generation. Clips remain
  downloadable for manual posting; revisit scheduling when a provider is chosen.
