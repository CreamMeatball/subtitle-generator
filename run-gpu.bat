@echo off
REM 자막 생성기 실행 (GPU 번역용 Python 3.12 venv 지정)
REM 이 파일을 더블클릭하면 SUBGEN_PYTHON 설정 + 앱 실행이 한 번에 됩니다.

set "SUBGEN_PYTHON=C:\SubtitleGenerator\venv312\Scripts\python.exe"
cd /d "%~dp0"

if not exist "%SUBGEN_PYTHON%" (
  echo [경고] Python venv를 찾을 수 없습니다: %SUBGEN_PYTHON%
  echo        경로가 다르면 이 파일에서 SUBGEN_PYTHON 값을 수정하세요.
  echo.
)

echo SUBGEN_PYTHON=%SUBGEN_PYTHON%
npm start
pause
