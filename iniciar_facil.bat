@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AmpereStore - Acceso facil
python -u scripts\iniciar_facil.py %*
if errorlevel 1 (
  echo.
  echo No se pudo iniciar AmpereStore. Revisa el mensaje anterior.
  pause
)
