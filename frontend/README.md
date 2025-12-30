# BMS Agent Dashboard (Vite + React + TS)

## Setup

Prerequisite: install Node.js (includes `npm`).

```bash
cd frontend
npm install
npm run dev
```

## Environment

Create `.env` (or copy `.env.example`):

- `VITE_API_BASE_URL=http://localhost:8000`

All frontend calls are made to `${import.meta.env.VITE_API_BASE_URL}/api/...`.
