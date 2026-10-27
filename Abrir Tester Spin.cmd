@echo off
cd /d "%~dp0"
if exist "target\release\tester-spin-rust.exe" (
    start "" "target\release\tester-spin-rust.exe"
) else (
    echo Compila primero con Construir.cmd
    pause
)
