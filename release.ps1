#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Creates a git tag matching the latest version in CHANGELOG.md and optionally pushes it.

.DESCRIPTION
    Reads CHANGELOG.md for the latest version entry (e.g., ## [1.0.0] - 2026-02-12),
    creates an annotated git tag (e.g., v1.0.0) with the changelog section as the message,
    and optionally pushes the tag to the remote.

.PARAMETER Push
    If specified, pushes the tag to the 'origin' remote after creation.

.PARAMETER Force
    If specified, overwrites an existing tag with the same name.

.PARAMETER DryRun
    If specified, shows what would happen without making any changes.

.EXAMPLE
    .\release.ps1                    # Create tag locally
    .\release.ps1 -Push              # Create tag and push to origin
    .\release.ps1 -DryRun            # Preview what would happen
    .\release.ps1 -Force -Push       # Overwrite existing tag and push
#>

param(
    [switch]$Push,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ── Read CHANGELOG.md ─────────────────────────────────────────────────
$changelogPath = Join-Path $PSScriptRoot "CHANGELOG.md"
if (-not (Test-Path $changelogPath)) {
    Write-Host "ERROR: CHANGELOG.md not found at $changelogPath" -ForegroundColor Red
    exit 1
}

$changelog = Get-Content $changelogPath -Raw

# ── Parse latest version ──────────────────────────────────────────────
# Matches: ## [1.0.0] - 2026-02-12
$versionPattern = '## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})'
$match = [regex]::Match($changelog, $versionPattern)

if (-not $match.Success) {
    Write-Host "ERROR: No version entry found in CHANGELOG.md" -ForegroundColor Red
    Write-Host "Expected format: ## [X.Y.Z] - YYYY-MM-DD" -ForegroundColor Yellow
    exit 1
}

$version = $match.Groups[1].Value
$date = $match.Groups[2].Value
$tagName = "v$version"

Write-Host "=== Release Tag ===" -ForegroundColor Cyan
Write-Host "  Version:  $version" -ForegroundColor White
Write-Host "  Tag:      $tagName" -ForegroundColor White
Write-Host "  Date:     $date" -ForegroundColor White
Write-Host ""

# ── Extract changelog section for this version ────────────────────────
# Get everything between this version header and the next version header (or end of file)
$sectionPattern = "## \[$([regex]::Escape($version))\] - $([regex]::Escape($date))([\s\S]*?)(?=\n## \[|^\[unreleased\]|\z)"
$sectionMatch = [regex]::Match($changelog, $sectionPattern, [System.Text.RegularExpressions.RegexOptions]::Multiline)

$tagMessage = "Release v$version`n`n"
if ($sectionMatch.Success) {
    $tagMessage += $sectionMatch.Groups[1].Value.Trim()
} else {
    $tagMessage += "Release $version ($date)"
}

# ── Check if tag already exists ───────────────────────────────────────
$existingTag = git tag -l $tagName 2>$null
if ($existingTag) {
    if ($Force) {
        Write-Host "WARNING: Tag $tagName already exists, will be overwritten (-Force)" -ForegroundColor Yellow
    } else {
        Write-Host "ERROR: Tag $tagName already exists." -ForegroundColor Red
        Write-Host "  Use -Force to overwrite, or update the version in CHANGELOG.md" -ForegroundColor Yellow
        exit 1
    }
}

# ── Check we're on a clean branch ─────────────────────────────────────
$status = git status --porcelain
if ($status -and -not $DryRun) {
    Write-Host "WARNING: You have uncommitted changes:" -ForegroundColor Yellow
    Write-Host $status -ForegroundColor Gray
    $confirm = Read-Host "Continue anyway? (y/N)"
    if ($confirm -ne 'y') {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
}

# ── Dry run ───────────────────────────────────────────────────────────
if ($DryRun) {
    Write-Host "[DRY RUN] Would create annotated tag: $tagName" -ForegroundColor Magenta
    Write-Host "[DRY RUN] Tag message:" -ForegroundColor Magenta
    Write-Host $tagMessage -ForegroundColor Gray
    if ($Push) {
        Write-Host "[DRY RUN] Would push tag to origin" -ForegroundColor Magenta
    }
    exit 0
}

# ── Create the tag ────────────────────────────────────────────────────
$forceFlag = if ($Force) { "-f" } else { "" }

# Write tag message to temp file to avoid shell escaping issues
$tempFile = [System.IO.Path]::GetTempFileName()
$tagMessage | Out-File -FilePath $tempFile -Encoding utf8

try {
    if ($Force) {
        git tag -a $tagName -F $tempFile --force
    } else {
        git tag -a $tagName -F $tempFile
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create tag" -ForegroundColor Red
        exit 1
    }

    Write-Host "Tag $tagName created successfully" -ForegroundColor Green
} finally {
    Remove-Item $tempFile -ErrorAction SilentlyContinue
}

# ── Push if requested ─────────────────────────────────────────────────
if ($Push) {
    Write-Host "Pushing tag $tagName to origin..." -ForegroundColor Yellow

    if ($Force) {
        git push origin $tagName --force
    } else {
        git push origin $tagName
    }

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Tag $tagName pushed to origin" -ForegroundColor Green
        Write-Host ""
        Write-Host "GitHub Release URL:" -ForegroundColor Cyan
        $repoUrl = (git remote get-url origin) -replace '\.git$', ''
        Write-Host "  $repoUrl/releases/tag/$tagName" -ForegroundColor White
    } else {
        Write-Host "ERROR: Failed to push tag" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Done! Next steps:" -ForegroundColor Cyan
if (-not $Push) {
    Write-Host "  1. Push tag:  git push origin $tagName" -ForegroundColor White
}
Write-Host "  $(if($Push){'1'}else{'2'}). Create GitHub Release from tag at:" -ForegroundColor White
$repoUrl = (git remote get-url origin) -replace '\.git$', ''
Write-Host "     $repoUrl/releases/new?tag=$tagName" -ForegroundColor White
