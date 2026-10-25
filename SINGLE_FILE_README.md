# Single-file builds

- `kisakcod-combined.html` — lightweight combined SP+MP, inlines JS+font, WASM stays external. Needs `kisakcod-sp.wasm` and `mp/kisakcod-mp.wasm` alongside. ~0.6 MB.
- `kisakcod-single.html` — fully self-contained, inlines JS+font+WASM. No external files except the game folder you pick. ~16 MB.

Both have a toggle for Singleplayer / Multiplayer (persisted in localStorage, overridable via `?mode=sp` or `?mode=mp`).

Serve with COOP/COEP headers for threading:
```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

Otherwise SharedArrayBuffer is disabled and MP may fail.
