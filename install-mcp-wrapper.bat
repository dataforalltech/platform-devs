@echo off
REM ============================================
REM MCP HTTP Wrapper Installer for Windows
REM Claude Code Desktop Integration
REM ============================================

setlocal enabledelayedexpansion

echo.
echo ========================================================
echo   MCP HTTP Wrapper Installer
echo ========================================================
echo.

REM Step 1: Check Python
echo [1/6] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python or add it to PATH
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo OK: Found %PYTHON_VERSION%
echo.

REM Step 2: Create directories
echo [2/6] Creating directories...
set WRAPPER_DIR=%USERPROFILE%\mcp-wrapper
set SETTINGS_DIR=%APPDATA%\Claude
set SETTINGS_FILE=%SETTINGS_DIR%\settings.json

if not exist "%WRAPPER_DIR%" (
    mkdir "%WRAPPER_DIR%"
    echo Created: %WRAPPER_DIR%
) else (
    echo Already exists: %WRAPPER_DIR%
)

if not exist "%SETTINGS_DIR%" (
    mkdir "%SETTINGS_DIR%"
    echo Created: %SETTINGS_DIR%
)
echo.

REM Step 3: Download wrapper script
echo [3/6] Downloading wrapper script...
REM Try to find wrapper in common locations
set WRAPPER_SOURCE=
if exist "mcp-http-wrapper.py" (
    set WRAPPER_SOURCE=mcp-http-wrapper.py
)
if exist "%USERPROFILE%\Downloads\mcp-http-wrapper.py" (
    set WRAPPER_SOURCE=%USERPROFILE%\Downloads\mcp-http-wrapper.py
)

if "!WRAPPER_SOURCE!"=="" (
    echo.
    echo ERROR: mcp-http-wrapper.py not found!
    echo.
    echo Please download from:
    echo   https://github.com/your-repo/mcp-http-wrapper.py
    echo.
    echo And place in one of these locations:
    echo   - Current directory
    echo   - Downloads folder
    echo.
    pause
    exit /b 1
)

copy "!WRAPPER_SOURCE!" "%WRAPPER_DIR%\mcp-http-wrapper.py" >nul
echo OK: Copied wrapper script
echo.

REM Step 4: Install dependencies
echo [4/6] Installing Python dependencies...
echo Running: pip install httpx
python -m pip install -q httpx
if errorlevel 1 (
    echo WARNING: Failed to install httpx automatically
    echo Run manually: pip install httpx
)
echo.

REM Step 5: Update settings.json
echo [5/6] Updating Claude Code settings...

REM Create a Python script to update JSON settings
set TEMP_SCRIPT=%TEMP%\update_settings.py
(
    echo import json
    echo import os
    echo from pathlib import Path
    echo.
    echo settings_file = Path(r"%SETTINGS_FILE%")
    echo settings_file.parent.mkdir(parents=True, exist_ok=True)
    echo.
    echo if settings_file.exists():
    echo     with open(settings_file, 'r') as f:
    echo         settings = json.load(f)
    echo else:
    echo     settings = {"mcpServers": {}, "preferences": {}}
    echo.
    echo if "mcpServers" not in settings:
    echo     settings["mcpServers"] = {}
    echo.
    echo settings["mcpServers"]["mcp-http-wrapper"] = {
    echo     "command": "python",
    echo     "args": [r"%WRAPPER_DIR%\mcp-http-wrapper.py"],
    echo     "disabled": False,
    echo     "alwaysAllow": ["mcp__mcp_http_wrapper__*"]
    echo }
    echo.
    echo with open(settings_file, 'w') as f:
    echo     json.dump(settings, f, indent=2)
    echo.
    echo print(f"Settings updated: {settings_file}")
) > "%TEMP_SCRIPT%"

python "%TEMP_SCRIPT%"
if errorlevel 1 (
    echo ERROR: Failed to update settings
    pause
    exit /b 1
)
del "%TEMP_SCRIPT%"
echo OK: Settings updated
echo.

REM Step 6: Test connection
echo [6/6] Testing connection to claude-dev...

set TEST_SCRIPT=%TEMP%\test_connection.py
(
    echo import sys
    echo try:
    echo     import httpx
    echo     response = httpx.get("http://claude-dev:8000/services", timeout=5)
    echo     if response.status_code == 200:
    echo         services = response.json()
    echo         print(f"✓ Connected to claude-dev")
    echo         print(f"✓ Found services")
    echo     else:
    echo         print(f"Warning: Status {response.status_code}")
    echo except Exception as e:
    echo     print(f"Warning: Could not connect to claude-dev:8000")
    echo     print(f"Error: {e}")
    echo     print("MCPs might not be running yet")
) > "%TEST_SCRIPT%"

python "%TEST_SCRIPT%" 2>nul
del "%TEST_SCRIPT%"
echo.

REM Final instructions
echo ========================================================
echo   ✓ Installation Complete!
echo ========================================================
echo.
echo NEXT STEPS:
echo.
echo 1. CLOSE Claude Code Desktop completely
echo    (Ctrl+Alt+Del ^> Task Manager ^> End task "Claude")
echo.
echo 2. REOPEN Claude Code Desktop
echo.
echo 3. VERIFY in Settings ^> MCP Servers
echo    Should show: mcp-http-wrapper (Connected)
echo.
echo 4. TEST in a new chat
echo    Ask: "What tools are available?"
echo    Should show ~170+ tools
echo.
echo IMPORTANT PATHS:
echo   Wrapper: %WRAPPER_DIR%\mcp-http-wrapper.py
echo   Settings: %SETTINGS_FILE%
echo.
echo TROUBLESHOOTING:
echo   If tools don't appear:
echo   - Check that claude-dev MCPs are running
echo   - Restart Claude Code Desktop
echo   - Check logs in temp folder
echo.
echo ========================================================
echo.

pause
