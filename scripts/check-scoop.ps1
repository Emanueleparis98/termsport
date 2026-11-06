# CI-only check in a disposable Scoop installation on the Windows runner.
$ErrorActionPreference = 'Stop'
$TermsportScoop = Join-Path $env:RUNNER_TEMP 'termsport-scoop-check'
$env:SCOOP = $TermsportScoop
$TermsportInstaller = Join-Path $env:RUNNER_TEMP 'install-scoop.ps1'
Invoke-WebRequest 'https://get.scoop.sh' -OutFile $TermsportInstaller
& $TermsportInstaller -ScoopDir $TermsportScoop -RunAsAdmin
if ($LASTEXITCODE -ne 0) { throw 'Cannot install Scoop in CI' }
$TermsportScoopCommand = Join-Path $TermsportScoop 'shims/scoop.ps1'
& $TermsportScoopCommand bucket add termsport https://github.com/Emanueleparis98/termsport
if ($LASTEXITCODE -ne 0) { throw 'Cannot add TermSport bucket' }
& $TermsportScoopCommand install termsport/termsport
if ($LASTEXITCODE -ne 0) { throw 'Cannot install TermSport through Scoop' }
& (Join-Path $TermsportScoop 'shims/termsport.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Scoop shim cannot launch TermSport' }
