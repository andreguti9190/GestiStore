@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AmpereStore - Configurar correo
python scripts\configurar_correo.py
echo.
pause
