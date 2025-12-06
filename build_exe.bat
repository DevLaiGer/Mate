@echo off
REM Build executable release version of mate

echo Building mate executable...

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

REM Clean previous builds
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

REM Build the executable
echo Running PyInstaller...
pyinstaller --clean --noconfirm mate.spec

if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

echo.
echo Build completed successfully!
echo Executable is located in: dist\mate.exe
echo.

pause

