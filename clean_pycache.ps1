param(
    [string]$Root = $PSScriptRoot,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$resolvedRoot = (Resolve-Path -LiteralPath $Root).ProviderPath
$rootWithSeparator = $resolvedRoot.TrimEnd('\') + '\'

Write-Host "Scanning for __pycache__ under: $resolvedRoot"

$pycacheDirs = Get-ChildItem -LiteralPath $resolvedRoot -Directory -Recurse -Force -Filter "__pycache__" |
    Sort-Object -Property FullName -Descending

if (-not $pycacheDirs) {
    Write-Host "No __pycache__ directories found."
    exit 0
}

foreach ($dir in $pycacheDirs) {
    $target = $dir.FullName
    $isInsideRoot = $target.Equals($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $target.StartsWith($rootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)

    if (-not $isInsideRoot) {
        throw "Refusing to remove path outside root: $target"
    }

    if ($DryRun) {
        Write-Host "[DRY RUN] Would remove: $target"
        continue
    }

    Write-Host "Removing: $target"
    Remove-Item -LiteralPath $target -Recurse -Force
}

if ($DryRun) {
    Write-Host "Found $($pycacheDirs.Count) __pycache__ director$(if ($pycacheDirs.Count -eq 1) { 'y' } else { 'ies' })."
} else {
    Write-Host "Removed $($pycacheDirs.Count) __pycache__ director$(if ($pycacheDirs.Count -eq 1) { 'y' } else { 'ies' })."
}
