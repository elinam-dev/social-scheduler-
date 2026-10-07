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
through the API. Each clip also has a persisted caption-style picker for the
default, minimal, and word-highlight presets. Saving trim or style changes
marks the clip pending until it is rendered again. Re-render any clip
individually and follow its live job progress. Renders burn captions using the
selected style and use a blurred-background layout at the clip's saved aspect
ratio. Videos without saved clips show an empty state.
Ready clips can be downloaded individually as MP4 files or together as a ZIP
containing the currently rendered clips.
The source selector also accepts supported public video URLs through yt-dlp;
URL imports require confirming that you own or have permission to process them.

Check the app with:

```sh
npm run lint
npm run typecheck
npm run build
```
