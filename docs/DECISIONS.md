# Decisions

- Stage 0 Compose ports bind to `127.0.0.1` by default. `.env.example` contains
  development-only credentials; replace them before exposing services to a network.
- The MinIO image uses a pinned `bitnamilegacy` release because the official image
  could not be pulled anonymously from Docker Hub or Quay during setup. This archived
  image starts successfully, but its base image may not receive future security
  updates; replace it with a maintained MinIO image source before production use.
