# Frontend

Bonfire's Next.js dashboard. See the [root README](../README.md) for the full
picture.

```sh
npm install
npm run dev        # http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL` if the backend is not on `http://localhost:8000`
(it is baked in at **build** time for production builds).

- UI components: shadcn/ui (`src/components/ui/`), charts: Recharts
- Theme tokens live in `src/app/globals.css` and `src/lib/theme.ts`
- API client: `src/lib/api.ts`

```sh
npm run lint       # eslint
npm run build      # production build (standalone output for Docker)
```
