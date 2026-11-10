@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AmpereStore - Acceso facil
where python >nul 2>nul
if not errorlevel 1 (
  python -u scripts\iniciar_facil.py %*
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    echo.
    echo ERROR: No se encontro Python 3 en esta PC.
    echo Instalalo desde https://www.python.org/downloads/ y volve a intentar.
    pause
    exit /b 1
  )
  py -3 -u scripts\iniciar_facil.py %*
)
if errorlevel 1 (
  echo.
  echo No se pudo iniciar AmpereStore. Revisa el mensaje anterior.
  pause
)
