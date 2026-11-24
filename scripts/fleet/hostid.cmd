@echo off
rem familia fleet host ID (Windows). See hostid.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0hostid.ps1" %*
