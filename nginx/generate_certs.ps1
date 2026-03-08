# Generate self-signed TLS certificate for local/dev use
# Run once from the repo root: .\nginx\generate_certs.ps1

$certsDir = Join-Path $PSScriptRoot "certs"

# Resolve openssl: prefer system PATH, then Git for Windows bundled binary
$opensslCmd = Get-Command openssl -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $opensslCmd) {
    $gitOpenssl = "C:\Program Files\Git\mingw64\bin\openssl.exe"
    if (Test-Path $gitOpenssl) { $opensslCmd = $gitOpenssl }
}
if (-not $opensslCmd) {
    Write-Error "openssl not found. Install Git for Windows (includes openssl) or OpenSSL for Windows."
    exit 1
}

New-Item -ItemType Directory -Force -Path $certsDir | Out-Null

& $opensslCmd req -x509 -nodes -days 3650 -newkey rsa:4096 `
    -keyout "$certsDir\server.key" `
    -out    "$certsDir\server.crt" `
    -subj "/C=IL/ST=Dev/L=Dev/O=pf9-mngt/CN=localhost" `
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

Write-Host "Self-signed cert written to $certsDir" -ForegroundColor Green
Write-Host "For production, replace server.crt and server.key with your real certificate files." -ForegroundColor Yellow
