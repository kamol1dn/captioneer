@echo off
rem ============================================================================
rem  Caption Engine - one-click setup and launch
rem
rem  Double-click this file to start the caption engine.
rem  The FIRST time it runs it installs everything the program needs
rem  (Python + libraries, ~4 GB download, 10-30 minutes depending on internet).
rem  Every time AFTER that it skips setup and opens the app in a few seconds.
rem ============================================================================
setlocal
cd /d "%~dp0"
title Caption Engine

rem ----------------------------------------------------------------------------
rem The project ships its own copy of FFmpeg (the tool that reads audio out of
rem video files) in the "ffmpeg-7.1" folder. This line tells Windows to use it
rem for this session only - it does not change anything else on the computer.
rem ----------------------------------------------------------------------------
set "PATH=%~dp0ffmpeg-7.1\bin;%PATH%"

rem If setup already finished once, this marker file exists - skip straight
rem to launching the app.
if exist "venv\.setup_complete" goto run

echo.
echo  ============================================================
echo   CAPTION ENGINE - FIRST TIME SETUP
echo  ============================================================
echo.
echo   This looks like the first time running the app on this
echo   computer, so it will now install everything it needs.
echo   This is automatic - you do not have to do anything.
echo.
echo   It downloads about 4 GB, so it can take 10-30 minutes.
echo   Please keep this window open until it says DONE.
echo.
pause

rem ============================================================================
rem  STEP 1 / 6 - Python
rem ============================================================================
echo.
echo [Step 1 of 6] Checking for Python 3.12...
echo               Python is the programming language the caption engine
echo               is written in. Version 3.12 specifically is required.
py -3.12 --version >nul 2>&1
if not errorlevel 1 goto have_python

echo               Python 3.12 was not found - installing it now with
echo               winget, the built-in Windows app installer.
echo               If Windows asks for permission, click Yes.
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto fail_python

rem A brand-new install sometimes is not visible to this window yet.
py -3.12 --version >nul 2>&1
if errorlevel 1 goto need_restart
:have_python
echo               OK - Python 3.12 is installed.

rem ============================================================================
rem  STEP 2 / 6 - Private workspace (virtual environment)
rem ============================================================================
echo.
echo [Step 2 of 6] Creating the app's private workspace ("venv" folder)...
echo               All the libraries get installed into this one folder
echo               inside the project, so nothing else on the computer
echo               is touched. Deleting the folder fully uninstalls them.
if exist "venv\Scripts\python.exe" goto have_venv
py -3.12 -m venv venv
if errorlevel 1 goto fail
:have_venv
echo               OK - workspace ready.

echo.
echo               Updating pip (the tool that downloads Python libraries)...
venv\Scripts\python -m pip install --upgrade pip --quiet
if errorlevel 1 goto fail

rem ============================================================================
rem  STEP 3 / 6 - PyTorch (the AI engine) - this is the big download
rem ============================================================================
echo.
echo [Step 3 of 6] Installing PyTorch, the AI engine that powers the
echo               speech recognition. THIS IS THE BIGGEST DOWNLOAD
echo               (2-3 GB) - it is normal for it to sit at the same
echo               percentage for a while. Please be patient.
where nvidia-smi >nul 2>&1
if errorlevel 1 goto cpu_torch

echo               An NVIDIA graphics card was detected - installing the
echo               GPU version, which transcribes much faster.
venv\Scripts\python -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto fail
goto torch_done

:cpu_torch
echo               No NVIDIA graphics card found - installing the regular
echo               version. Everything still works, transcription is just
echo               slower.
venv\Scripts\python -m pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0
if errorlevel 1 goto fail
:torch_done
echo               OK - PyTorch installed.

rem ============================================================================
rem  STEP 4 / 6 - The rest of the libraries
rem ============================================================================
echo.
echo [Step 4 of 6] Installing the remaining libraries (speech recognition,
echo               subtitle rendering, image handling)...
venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo               OK - libraries installed.

rem ============================================================================
rem  STEP 5 / 6 - FFmpeg wiring
rem ============================================================================
echo.
echo [Step 5 of 6] Copying the bundled FFmpeg files into the AI libraries...
echo               One of the libraries needs FFmpeg's files sitting right
echo               next to it or it refuses to start. This fixes that.
if not exist "venv\Lib\site-packages\torchcodec\" goto fail_torchcodec
copy /y "ffmpeg-7.1\bin\av*.dll"       "venv\Lib\site-packages\torchcodec\" >nul
copy /y "ffmpeg-7.1\bin\sw*.dll"       "venv\Lib\site-packages\torchcodec\" >nul
copy /y "ffmpeg-7.1\bin\postproc*.dll" "venv\Lib\site-packages\torchcodec\" >nul
echo               OK - FFmpeg wired up.

rem ============================================================================
rem  STEP 6 / 6 - Final check
rem ============================================================================
echo.
echo [Step 6 of 6] Double-checking that everything loads correctly...
venv\Scripts\python -c "import torch; import torchcodec; import whisperx" >nul
if errorlevel 1 goto fail_verify
ffmpeg -version >nul 2>&1
if errorlevel 1 goto fail_verify

rem Leave the marker so future launches skip all of the above.
echo ok> "venv\.setup_complete"

echo.
echo  ============================================================
echo   DONE - setup finished successfully!
echo  ============================================================
echo.
echo   One heads-up: the FIRST TIME you transcribe a video, the app
echo   downloads the AI speech models themselves (a few more GB).
echo   That only happens once - after that everything is fast.
echo.

rem ============================================================================
rem  Launch the app
rem ============================================================================
:run
echo Starting the Caption Engine...
echo (Keep this black window open - it closes when you close the app.
echo  If something goes wrong, the error appears here.)
venv\Scripts\python.exe -m caption_engine.gui
if errorlevel 1 goto fail_app
exit /b 0

rem ============================================================================
rem  Error messages
rem ============================================================================
:fail_python
echo.
echo  PROBLEM: Python could not be installed automatically.
echo  FIX:     Install it by hand - open this page in a browser:
echo           https://www.python.org/downloads/release/python-3129/
echo           download "Windows installer (64-bit)", run it, then
echo           double-click run.bat again.
pause
exit /b 1

:need_restart
echo.
echo  Python was just installed, but this window cannot see it yet.
echo  FIX: Simply close this window and double-click run.bat again.
echo       Setup will continue where it left off.
pause
exit /b 1

:fail_torchcodec
echo.
echo  PROBLEM: The "torchcodec" library folder was not found, so the
echo           FFmpeg files could not be copied into it.
echo  FIX:     Delete the "venv" folder inside the project and
echo           double-click run.bat again to redo the setup.
pause
exit /b 1

:fail_verify
echo.
echo  PROBLEM: Setup finished installing but the final check failed.
echo  FIX:     Take a photo/screenshot of this window and send it to
echo           Kamoliddin. Do not delete anything yet.
pause
exit /b 1

:fail_app
echo.
echo  The app closed because of an error - see the message above.
echo  If you cannot fix it, take a screenshot of this window and
echo  send it to Kamoliddin.
pause
exit /b 1

:fail
echo.
echo  PROBLEM: Something went wrong during the step shown above.
echo           This is usually the internet connection dropping.
echo  FIX:     Check the internet is working, then close this window
echo           and double-click run.bat again - setup continues where
echo           it left off.
pause
exit /b 1
