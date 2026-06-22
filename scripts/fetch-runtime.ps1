# 빌드용 런타임 자동 수집: 독립 실행형 Python + ffmpeg 를 공식 경로에서 받아
# runtime/python, runtime/ffmpeg 에 배치한다. (빌드 전 1회 실행)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root "runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

# ---------- 1) Python (python-build-standalone, 공식 릴리스) ----------
# 최신 릴리스를 쓰려면 아래 URL을 https://github.com/astral-sh/python-build-standalone/releases 에서 갱신.
$pyUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/20241016/cpython-3.12.7+20241016-x86_64-pc-windows-msvc-install_only.tar.gz"
$pyTar = Join-Path $env:TEMP "subgen-python.tar.gz"
Write-Host "[1/2] Python 다운로드..."
Invoke-WebRequest -Uri $pyUrl -OutFile $pyTar
$pyExtract = Join-Path $env:TEMP "subgen-python"
Remove-Item -Recurse -Force $pyExtract -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $pyExtract | Out-Null
tar -xzf $pyTar -C $pyExtract          # Windows 10+ 에 tar 내장
$pySrc = Join-Path $pyExtract "python"  # install_only 산출물: <extract>/python/python.exe
$pyDst = Join-Path $runtime "python"
Remove-Item -Recurse -Force $pyDst -ErrorAction SilentlyContinue
Copy-Item -Recurse $pySrc $pyDst
if (-not (Test-Path (Join-Path $pyDst "python.exe"))) { throw "python.exe 를 찾지 못했습니다." }
Write-Host "      Python 준비됨: $pyDst\python.exe"

# ---------- 2) ffmpeg (gyan.dev 공식 빌드) ----------
$ffUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$ffZip = Join-Path $env:TEMP "subgen-ffmpeg.zip"
Write-Host "[2/2] ffmpeg 다운로드..."
Invoke-WebRequest -Uri $ffUrl -OutFile $ffZip
$ffExtract = Join-Path $env:TEMP "subgen-ffmpeg"
Remove-Item -Recurse -Force $ffExtract -ErrorAction SilentlyContinue
Expand-Archive -Path $ffZip -DestinationPath $ffExtract -Force
$ffBin = Get-ChildItem -Recurse -Path $ffExtract -Filter "ffmpeg.exe" | Select-Object -First 1
$ffSrcDir = Split-Path -Parent $ffBin.FullName
$ffDst = Join-Path $runtime "ffmpeg"
New-Item -ItemType Directory -Force -Path $ffDst | Out-Null
Copy-Item (Join-Path $ffSrcDir "ffmpeg.exe") $ffDst -Force
Copy-Item (Join-Path $ffSrcDir "ffprobe.exe") $ffDst -Force
Write-Host "      ffmpeg 준비됨: $ffDst\ffmpeg.exe"

Write-Host "`n완료! 이제 'npm run dist' 로 설치 파일을 빌드하세요."
