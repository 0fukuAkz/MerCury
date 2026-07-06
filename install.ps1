<#
.SYNOPSIS
    MerCury automated installer for Windows (PowerShell).

.DESCRIPTION
    Installs MerCury into an isolated virtualenv, initialises its database, and
    leaves a login-ready local instance. Works in two modes automatically:

      * SOURCE mode  - run from a checkout of the MerCury repo (pyproject.toml
                       with `name = "mercury"` beside this script).
      * PACKAGE mode - run anywhere else; installs `mercury` from PyPI.

    Virtualenv backend: prefers `uv` when installed (fast, and the only backend
    that works with uv-managed / python-build-standalone interpreters - stdlib
    `python -m venv` crashes on those). Falls back to `python -m venv` + pip.

    Safety: never overwrites an existing .env; reuses an existing virtualenv
    unless -Recreate is passed.

.PARAMETER Venv       Virtualenv location (default: .venv)
.PARAMETER Python     Explicit interpreter instead of auto-detecting 3.12
.PARAMETER Extras     Comma list: postgres,redis,worker,observability,pdf,geo,all
.PARAMETER Dev        Editable install (pip install -e) + the [dev] extra
.PARAMETER Recreate   Delete and rebuild the virtualenv
.PARAMETER NoUv       Force stdlib venv + pip even if uv is installed
.PARAMETER NoBootstrap  On a bare system (no Python + no uv), fail instead of auto-installing uv
.PARAMETER NoDb       Skip `mercury db migrate`
.PARAMETER NoEnv      Do not generate a starter .env
.PARAMETER Uninstall  Remove the virtualenv (add -Purge to also delete .env + local DB)
.PARAMETER Purge      With -Uninstall: also delete .env + the local database
.PARAMETER Yes        Non-interactive; never prompt

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -Extras postgres,redis
.EXAMPLE
    .\install.ps1 -Dev
#>
[CmdletBinding()]
param(
    [string] $Venv    = ".venv",
    [string] $Python  = "",
    [string] $Extras  = "",
    [switch] $Dev,
    [switch] $Recreate,
    [switch] $NoUv,
    [switch] $NoBootstrap,
    [switch] $NoDb,
    [switch] $NoEnv,
    [switch] $Uninstall,
    [switch] $Purge,
    [switch] $Yes
)

$ErrorActionPreference = "Stop"
$RequiredPy = "3.12"   # pyproject: requires-python >=3.12,<3.13

# --- pretty output ---------------------------------------------------------
function Step($m) { Write-Host "==> $m" -ForegroundColor Blue }
function Ok($m)   { Write-Host "    [ok] $m" -ForegroundColor Green }
function Info($m) { Write-Host "    $m" }
function Warn($m) { Write-Host "    [!] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

# Install uv on a bare system, then make it usable in THIS session. uv fetches a
# managed Python 3.12 for us and adds itself to PATH for future shells.
function Install-Uv {
    Step "No Python $RequiredPy and no uv found - bootstrapping uv"
    Info "Installing uv from https://astral.sh/uv (it will fetch Python $RequiredPy)"
    try {
        Invoke-Expression (Invoke-RestMethod https://astral.sh/uv/install.ps1)
    } catch {
        Die "uv install failed: $_"
    }
    # uv installs to %USERPROFILE%\.local\bin (older builds: ~\.cargo\bin).
    $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Die "uv installed but not on PATH - open a new terminal and re-run .\install.ps1"
    }
    Ok "uv ready"
}

# Reverse an install: always remove the virtualenv; with -Purge also delete the
# generated .env and the LOCAL database / salt / logs. Never touches source or an
# external Postgres database.
function Invoke-Uninstall {
    Write-Host "MerCury uninstaller (Windows)`n" -ForegroundColor White

    $pyproj = Join-Path $ScriptDir "pyproject.toml"
    $installDir = if ((Test-Path $pyproj) -and (Select-String -Path $pyproj -Pattern '^name = "mercury"' -Quiet)) { $ScriptDir } else { (Get-Location).Path }
    $envFile = Join-Path $installDir ".env"
    $venvPy  = Join-Path $Venv "Scripts\python.exe"

    $dataDir = ""; $logDir = ""; $dbPath = ""
    if ($Purge -and (Test-Path $venvPy)) {
        if (Test-Path $envFile) {
            Get-Content $envFile | ForEach-Object {
                if ($_ -match '^\s*([^#=][^=]*)=(.*)$') {
                    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
                }
            }
        }
        $dataDir = (& $venvPy -c "from mercury.utils import app_dirs as a; print(a.get_data_dir())" 2>$null | Out-String).Trim()
        $logDir  = (& $venvPy -c "from mercury.utils import app_dirs as a; print(a.get_log_dir())"  2>$null | Out-String).Trim()
        $dbPath  = (& $venvPy -c "from mercury.utils import app_dirs as a; print(a.get_db_path())"  2>$null | Out-String).Trim()
    }

    Step "Will remove"
    if (Test-Path $Venv) { Info "* virtualenv:  $Venv" } else { Info "* virtualenv:  (none at $Venv)" }
    if ($Purge) {
        if (Test-Path $envFile) { Info "* .env:        $envFile" }
        if ($dbPath -like "sqlite:*") { Info "* database:    $($dbPath -replace '^sqlite:///','')" }
        elseif ($dbPath)             { Warn "database is external ($dbPath) - NOT removed" }
        if ($dataDir) { Info "* data dir:    $dataDir  (DB + encryption salt)" }
        if ($logDir)  { Info "* log dir:     $logDir" }
    } else {
        Info "(keeping .env + database - pass -Purge to remove them too)"
    }

    if (-not $Yes) {
        $reply = Read-Host "`nProceed with removal? [y/N]"
        if ($reply -notmatch '^[yY]') { Info "Aborted - nothing removed."; exit 0 }
    }

    Step "Removing"
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv; Ok "virtualenv" }
    if ($Purge) {
        if (Test-Path $envFile) { Remove-Item -Force $envFile; Ok ".env" }
        if ($dataDir -and (Test-Path $dataDir)) { Remove-Item -Recurse -Force $dataDir; Ok "data dir" }
        if ($logDir  -and (Test-Path $logDir))  { Remove-Item -Recurse -Force $logDir;  Ok "log dir" }
    }
    Write-Host "`n[ok] MerCury uninstalled." -ForegroundColor Green
    exit 0
}

# Location of this script - SOURCE-mode detection is location-based.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Uninstall) { Invoke-Uninstall }   # exits (prints its own banner)

Write-Host "MerCury installer (Windows)`n" -ForegroundColor White

# --- 1. locate Python 3.12 -------------------------------------------------
# requires-python is exactly 3.12: a 3.11/3.13 interpreter makes pip fail with
# an opaque resolver error, so validate the minor version up front. Returns the
# full interpreter path, or $null if none is on PATH (uv may still provide one).
Step "Locating Python $RequiredPy"

function Resolve-Py312 {
    param([string] $Explicit)
    if ($Explicit) {
        $m = (& $Explicit -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null | Out-String).Trim()
        if ($m -ne $RequiredPy) { Die "$Explicit is Python '$m'; MerCury needs exactly $RequiredPy." }
        return (& $Explicit -c "import sys;print(sys.executable)" | Out-String).Trim()
    }
    $cands = @(
        @{ e = "py";      a = @("-3.12") },
        @{ e = "python";  a = @() },
        @{ e = "python3"; a = @() }
    )
    foreach ($c in $cands) {
        if (Get-Command $c.e -ErrorAction SilentlyContinue) {
            $m = (& $c.e @($c.a) -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null | Out-String).Trim()
            if ($m -eq $RequiredPy) {
                return (& $c.e @($c.a) -c "import sys;print(sys.executable)" | Out-String).Trim()
            }
        }
    }
    return $null
}

$FoundPy = Resolve-Py312 -Explicit $Python
$UseUv   = (-not $NoUv) -and [bool](Get-Command uv -ErrorAction SilentlyContinue)

# Truly fresh machine: no Python 3.12 and no uv. Auto-install uv (unless opted
# out), which then downloads a managed Python 3.12 and handles PATH.
if (-not $FoundPy -and -not $UseUv -and -not $NoUv -and -not $NoBootstrap) {
    Install-Uv
    $UseUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)
}

if ($FoundPy) {
    $PySpec = $FoundPy
    Ok "Using $FoundPy"
} elseif ($UseUv) {
    $PySpec = $RequiredPy   # let uv fetch/select a managed 3.12
    Ok "No system Python $RequiredPy on PATH - uv will provide a managed $RequiredPy"
} else {
    Write-Host "[X] No Python $RequiredPy interpreter found." -ForegroundColor Red
    Write-Host @"

    MerCury requires Python $RequiredPy (not 3.11, not 3.13). Either install it:
      winget:  winget install Python.Python.3.12
      or:      https://www.python.org/downloads/release/python-3120/
    ...or install uv (which can fetch 3.12 for you):
      powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    Then re-run:  .\install.ps1
"@
    exit 1
}
if ($UseUv) { Info "Backend: uv $((uv --version) -replace 'uv ','')" }
else        { Info "Backend: python -m venv + pip" }

# --- 2. install source: SOURCE vs PACKAGE ----------------------------------
Step "Selecting install source"
$InstallMode = "package"
$InstallDir  = (Get-Location).Path
$pyproject   = Join-Path $ScriptDir "pyproject.toml"
if ((Test-Path $pyproject) -and (Select-String -Path $pyproject -Pattern '^name = "mercury"' -Quiet)) {
    $InstallMode = "source"
    $InstallDir  = $ScriptDir
    Ok "Source checkout detected - installing from $InstallDir"
} else {
    Ok "No checkout here - installing the released 'mercury' package from PyPI"
}

# --- 3. create / reuse virtualenv ------------------------------------------
Step "Preparing virtualenv: $Venv"
if ((Test-Path $Venv) -and $Recreate) { Warn "Removing existing virtualenv (-Recreate)"; Remove-Item -Recurse -Force $Venv }
if (Test-Path $Venv) {
    Ok "Reusing existing virtualenv (pass -Recreate to rebuild)"
} else {
    if ($UseUv) {
        & uv venv --seed --python $PySpec $Venv
    } else {
        & $FoundPy -m venv $Venv
    }
    if ($LASTEXITCODE -ne 0) { Die "Failed to create virtualenv at $Venv" }
    Ok "Created virtualenv"
}
$VenvPy      = Join-Path $Venv "Scripts\python.exe"
$VenvMercury = Join-Path $Venv "Scripts\mercury.exe"
if (-not (Test-Path $VenvPy)) { Die "Virtualenv looks broken: $VenvPy missing" }

# --- 4. install MerCury ----------------------------------------------------
Step "Installing MerCury and dependencies"

$extraList = $Extras
if ($Dev -and ($extraList -notmatch '(^|,)dev(,|$)')) {
    $extraList = if ($extraList) { "$extraList,dev" } else { "dev" }
}
$bracket = if ($extraList) { "[$extraList]" } else { "" }

if ($InstallMode -eq "source") { $target = "$InstallDir$bracket" } else { $target = "mercury$bracket" }
$editable = $Dev -and ($InstallMode -eq "source")

if ($UseUv) {
    $uvArgs = @("pip", "install", "--python", $VenvPy)
    if ($editable) { $uvArgs += "-e" }
    $uvArgs += $target
    Info "uv $($uvArgs -join ' ')"
    & uv @uvArgs
} else {
    Info "Upgrading pip toolchain..."
    & $VenvPy -m pip install --quiet --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { Die "pip bootstrap failed" }
    $pipArgs = @("-m", "pip", "install")
    if ($editable) { $pipArgs += "-e" }
    $pipArgs += $target
    Info "pip install $($pipArgs[2..($pipArgs.Length-1)] -join ' ')"
    & $VenvPy @pipArgs
}
if ($LASTEXITCODE -ne 0) { Die "Install failed. If MerCury isn't on PyPI yet, run this from a repo checkout." }
Ok "Installed MerCury"

# --- 5. generate starter .env (only if absent) -----------------------------
# The app creates the admin on first boot only when ADMIN_USERNAME/PASSWORD/EMAIL
# are all present; write all three + a strong SECRET_KEY so it's login-ready.
$EnvFile      = Join-Path $InstallDir ".env"
$GeneratedEnv = $false
$AdminUser    = "admin"
$AdminPass    = ""
if (-not $NoEnv) {
    Step "Configuring environment (.env)"
    if (Test-Path $EnvFile) {
        Ok "Keeping existing .env (not overwritten)"
    } else {
        $SecretKey = & $VenvPy -c "import secrets; print(secrets.token_urlsafe(48))"
        $AdminPass = & $VenvPy -c "import secrets; print(secrets.token_urlsafe(18))"
        @"
# MerCury local configuration - generated by install.ps1
FLASK_ENV=development
SECRET_KEY=$SecretKey
ADMIN_USERNAME=$AdminUser
ADMIN_PASSWORD=$AdminPass
ADMIN_EMAIL=admin@localhost
# DATABASE_URL unset => SQLite in your user-data dir. For Postgres install with
# -Extras postgres and set e.g.:
# DATABASE_URL=postgresql://mercury:mercury@localhost:5432/mercury
"@ | Set-Content -Path $EnvFile -Encoding UTF8
        $GeneratedEnv = $true
        Ok "Wrote $EnvFile"
    }
}

# --- 6. initialise the database --------------------------------------------
# `mercury` does not auto-load .env - load it into this process before migrate.
function Import-DotEnv($path) {
    if (-not (Test-Path $path)) { return }
    Get-Content $path | ForEach-Object {
        if ($_ -match '^\s*([^#=][^=]*)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}
if (-not $NoDb) {
    Step "Initialising the database"
    Import-DotEnv $EnvFile
    & $VenvMercury db migrate
    if ($LASTEXITCODE -eq 0) { Ok "Schema is at head" }
    else { Warn "Migration did not complete. For Postgres, ensure the server is up and DATABASE_URL is set, then: mercury db migrate" }
}

# --- 7. next steps ---------------------------------------------------------
Write-Host "`n[ok] MerCury is installed.`n" -ForegroundColor Green
Write-Host "Start it" -ForegroundColor White
# NOTE: run.py uses gunicorn + eventlet, which do not run on Windows - use the
# CLI dev runner here. It does not read .env, so load it into the session first.
Write-Host @"
    & $Venv\Scripts\Activate.ps1
    Get-Content .env | Where-Object { `$_ -match '^\s*[^#].*=' } | ForEach-Object {
        `$k,`$v = `$_ -split '=',2; [Environment]::SetEnvironmentVariable(`$k.Trim(), `$v.Trim(), 'Process') }
    mercury start server            # -> http://127.0.0.1:5000
"@
Write-Host "`nLog in" -ForegroundColor White
if ($GeneratedEnv) {
    Write-Host "    username: $AdminUser"
    Write-Host "    password: $AdminPass   (saved in .env - change after first login)"
} else {
    Info "Use the ADMIN_USERNAME / ADMIN_PASSWORD from your .env"
}
Write-Host "`nOther commands:  mercury --help  |  mercury db current" -ForegroundColor DarkGray
