@echo off
cd /d "%~dp0"
cargo build --release
if errorlevel 1 pause
