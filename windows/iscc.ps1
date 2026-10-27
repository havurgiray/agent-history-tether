# Prints the path of Inno Setup 6's compiler, ISCC.exe, installing it for
# this user when it is missing (as on a fresh CI machine): Chocolatey's
# package if Chocolatey is there, else Inno Setup 6.7.3 from its GitHub
# release, run only when it is the file whose SHA-256 is below.
$ProgressPreference = "SilentlyContinue"
$Url = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
$Sha256 = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"
function Found {
  return @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
           "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
$iscc = Found
if (-not $iscc -and (Get-Command choco -ErrorAction SilentlyContinue)) {
  choco install innosetup -y --no-progress | Out-Null
  $iscc = Found
}
if (-not $iscc) {
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
  $dir = Join-Path ([IO.Path]::GetTempPath()) ("aht-innosetup-" + [guid]::NewGuid())
  New-Item -ItemType Directory $dir | Out-Null
  $is = Join-Path $dir "innosetup-6.7.3.exe"
  function Fail($why) { Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue; Write-Error $why; exit 1 }
  try {
    Invoke-WebRequest -UseBasicParsing $Url -OutFile $is -ErrorAction Stop
  } catch {
    Fail "Inno Setup 6 could not be downloaded from ${Url}: $($_.Exception.Message)"
  }
  $head = New-Object byte[] 2                  # a program starts with "MZ"
  $fh = [IO.File]::OpenRead($is); $n = $fh.Read($head, 0, 2); $fh.Close()
  if ($n -ne 2 -or $head[0] -ne 0x4D -or $head[1] -ne 0x5A) {
    Fail "The download from $Url is not a program; it was not run"
  }
  $hash = (Get-FileHash -Algorithm SHA256 $is).Hash
  if ($hash -ne $Sha256) {
    Fail "The download from $Url is not the expected Inno Setup 6.7.3 (SHA-256 $hash); it was not run"
  }
  Start-Process -Wait $is -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CURRENTUSER"
  Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
  $iscc = Found
}
if (-not $iscc) { Write-Error "Inno Setup 6 could not be installed"; exit 1 }
$iscc
