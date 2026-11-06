param(
    [string]$Wheel = "",
    [string]$Python = "3.13",
    [switch]$NoPath
)
$ErrorActionPreference = "Stop"
$TermsportTemp = Join-Path ([IO.Path]::GetTempPath()) ("termsport-" + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $TermsportTemp | Out-Null
try {
    if (-not $Wheel) {
        $TermsportBase = 'https://github.com/Emanueleparis98/termsport/releases'
        $TermsportRelease = Invoke-RestMethod -Uri "$TermsportBase/latest/download/latest.json"
        $TermsportVersion = [string]$TermsportRelease.version
        if ($TermsportVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Versione della release non valida.' }
        $TermsportWheelName = "termsport-$TermsportVersion-py3-none-any.whl"
        $Wheel = Join-Path $TermsportTemp $TermsportWheelName
        Invoke-WebRequest -Uri "$TermsportBase/download/v$TermsportVersion/$TermsportWheelName" -OutFile $Wheel
        Invoke-WebRequest -Uri "$TermsportBase/download/v$TermsportVersion/SHA256SUMS" -OutFile (Join-Path $TermsportTemp 'SHA256SUMS')
    }
    $Wheel = (Resolve-Path -LiteralPath $Wheel).Path
    $TermsportChecksums = Join-Path (Split-Path -Parent $Wheel) 'SHA256SUMS'
    if (-not (Test-Path -LiteralPath $TermsportChecksums)) { throw 'Manca SHA256SUMS accanto al pacchetto.' }
    $TermsportName = [IO.Path]::GetFileName($Wheel)
    $TermsportExpected = @((Get-Content -LiteralPath $TermsportChecksums) | ForEach-Object {
        if ($_ -match '^([a-fA-F0-9]{64})\s+(.+)$' -and $Matches[2] -ceq $TermsportName) { $Matches[1] }
    })
    # .NET works in Windows PowerShell 5.1 and PowerShell 7, without depending
    # on the optional/autoloaded Get-FileHash cmdlet module.
    $TermsportHasher = [Security.Cryptography.SHA256]::Create()
    $TermsportInputFile = [IO.File]::OpenRead($Wheel)
    try {
        $TermsportActual = [BitConverter]::ToString($TermsportHasher.ComputeHash($TermsportInputFile)).Replace('-', '')
    } finally {
        $TermsportInputFile.Dispose()
        $TermsportHasher.Dispose()
    }
    if ($TermsportExpected.Count -ne 1 -or $TermsportActual -ine $TermsportExpected[0]) { throw 'Checksum del pacchetto non valido; installazione annullata.' }
    $TermsportUv = $env:TERMSPORT_UV
    if (-not $TermsportUv) {
        $TermsportUvInfo = Get-Command uv -ErrorAction SilentlyContinue
        if ($TermsportUvInfo) { $TermsportUv = $TermsportUvInfo.Source }
    }
    if (-not $TermsportUv) {
        $TermsportUv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
        if (-not (Test-Path -LiteralPath $TermsportUv)) {
            Write-Host 'Installo uv dal sito ufficiale Astral…'
            $TermsportOldNoPath = $env:UV_NO_MODIFY_PATH
            try {
                $env:UV_NO_MODIFY_PATH = '1'
                Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -OutFile (Join-Path $TermsportTemp 'uv-install.ps1')
                & (Join-Path $TermsportTemp 'uv-install.ps1')
                if (-not (Test-Path -LiteralPath $TermsportUv)) { throw 'Installazione di uv non completata.' }
            } finally { $env:UV_NO_MODIFY_PATH = $TermsportOldNoPath }
        }
    }
    & $TermsportUv tool install --python $Python --force $Wheel
    if ($LASTEXITCODE -ne 0) { throw 'Installazione di TermSport non riuscita.' }
    if (-not $NoPath) {
        & $TermsportUv tool update-shell
        if ($LASTEXITCODE -ne 0) { throw 'Aggiornamento PATH non riuscito.' }
    }
    $TermsportBin = ((& $TermsportUv tool dir --bin) -join [Environment]::NewLine).Trim()
    & (Join-Path $TermsportBin 'termsport.exe') --version
    if ($LASTEXITCODE -ne 0) { throw 'Verifica del comando termsport non riuscita.' }
    Write-Host 'Installazione completata. Avvia con: termsport'
    Write-Host 'Se il comando non viene riconosciuto, riapri il terminale per aggiornare PATH.'
} finally {
    Remove-Item -LiteralPath $TermsportTemp -Recurse -Force -ErrorAction SilentlyContinue
}
