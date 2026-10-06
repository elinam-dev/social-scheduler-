# Local Clip Studio web app

This Next.js App Router app provides a local video upload page and a typed client
for the FastAPI project, upload, job, transcript, and clip endpoints. Upload
progress is shown in the browser; processing updates arrive over server-sent
events, and ready clips appear in a ranked preview list.

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
is in `src/lib/api.ts`. The upload page creates a project, uploads its video,
then listens to the job event stream until processing succeeds or fails. Once
processing succeeds, the page loads saved clips, displays their titles and
scores, and plays ready previews from the local API. The transcript trim editor
sets clip boundaries from transcript segments or exact seconds and saves them
through the API. Videos without saved clips show an empty state.

Check the app with:

```sh
npm run lint
npm run typecheck
npm run build
```
