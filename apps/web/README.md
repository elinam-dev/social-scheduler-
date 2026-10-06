# Local Clip Studio web app

This Next.js App Router app provides the local web interface and a typed client
for the FastAPI project, upload, job, and transcript endpoints.

## Run locally

From this directory, copy `env.local.example` to `.env.local`. Set
`CLIPPER_API_SERVER_URL` to the address where the API is reachable from the Next.js
server. The example uses port 8001; use port 8000 if the API uses its default
Compose port.

```sh
npm run dev
```

Open `http://localhost:3000`. Requests to `/backend-api/*` are proxied by Next.js
to `CLIPPER_API_SERVER_URL`, avoiding browser CORS configuration. The API client
is in `src/lib/api.ts`.

Check the app with:

```sh
npm run lint
npm run typecheck
npm run build
```
