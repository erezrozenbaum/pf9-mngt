# nginx/certs/

Place TLS certificate files here before starting the nginx container:

| File | Description |
|------|-------------|
| `server.crt` | TLS certificate (PEM) — concatenate your cert + any intermediates |
| `server.key` | Private key (PEM, unencrypted) |

## Development (self-signed)

Run from the repo root:

```powershell
.\nginx\generate_certs.ps1
```

This generates a 10-year self-signed certificate valid for `localhost`.
Your browser will show a security warning — that is expected for self-signed certs.

## Production

Replace the two files with your real certificate before deploying.  
If you use Let's Encrypt, the files are typically named `fullchain.pem` → `server.crt` and `privkey.pem` → `server.key`.

The `certs/` directory is listed in `.gitignore` — private keys are never committed.
