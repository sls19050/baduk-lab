# Harvest the games you commented on, then serve the quiz.
#
# Run it from anywhere -- it finds its own repo and uses the venv's
# executable directly, so you never have to activate anything:
#
#   .\quiz.ps1                 # your own review notes, 20 problems
#   .\quiz.ps1 -Limit 5        # a short session
#   .\quiz.ps1 -Source all     # KataGo's finds too (notes still come first)
#   .\quiz.ps1 -SkipHarvest    # don't rescan; drill what's already there
#   .\quiz.ps1 -All           # whole deck, even what isn't due yet
#
# Ctrl+C stops the server. Your answers are saved as you go.

param(
    [int]$Limit = 20,
    [ValidateSet("note", "katago", "all")] [string]$Source = "note",
    [string]$Out = "report",
    [switch]$SkipHarvest,
    [switch]$All
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$exe = Join-Path $repo ".venv\Scripts\baduk-lab.exe"

if (-not (Test-Path $exe)) {
    Write-Error "No venv at $exe -- from $repo, run: python -m venv .venv; .venv\Scripts\python.exe -m pip install -e ."
}

Push-Location $repo
try {
    if (-not $SkipHarvest) {
        # Cheap: reads the KataGo analysis already saved in each SGF, so no
        # GPU and no engine start. This is what picks up games you reviewed
        # since last time; it keeps the review progress you already have.
        & $exe notes
        if ($LASTEXITCODE -ne 0) { Write-Error "notes failed -- nothing new served." }
    }

    Write-Host ""
    Write-Host "Starting the quiz. The URL below opens in your browser; Ctrl+C here stops it." -ForegroundColor Cyan
    Write-Host ""

    $extra = @()
    if ($All) { $extra += "--ignore-due" }

    & $exe review --source $Source --out $Out --limit $Limit --html @extra
}
finally {
    Pop-Location
}
