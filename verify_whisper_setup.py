"""Quick verification script to check if Whisper.cpp is properly set up."""

import sys
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def check_whisper_setup():
    """Verify whisper.cpp setup before running the main app."""
    
    print("=" * 60)
    print("WHISPER.CPP SETUP VERIFICATION")
    print("=" * 60)
    print()
    
    issues = []
    warnings = []
    
    # Check 1: Whisper executable
    print("1. Checking for whisper.cpp executable...")
    
    # First check if .env specifies a path
    env_whisper_path = None
    env_file = Path(".env")
    if env_file.exists():
        try:
            content = env_file.read_text()
            for line in content.split('\n'):
                if line.strip().startswith('MATE_WHISPER_EXECUTABLE='):
                    env_whisper_path = line.split('=', 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass
    
    whisper_found = None
    
    # Check .env path first
    if env_whisper_path:
        env_path = Path(env_whisper_path)
        if env_path.exists():
            whisper_found = env_path
            print(f"   [OK] Found from .env: {env_path.absolute()}")
    
    # Fallback to default paths
    if not whisper_found:
        whisper_paths = [
            Path("whisper.exe"),
            Path("main.exe"),
            Path("whisper.cpp/whisper.exe"),
            Path("whisper.cpp/build/bin/Release/whisper.exe"),
            Path("whisper.cpp/build/bin/Release/main.exe"),
        ]
        
        for path in whisper_paths:
            if path.exists():
                whisper_found = path
                print(f"   [OK] Found: {path.absolute()}")
                break
    
    if not whisper_found:
        issues.append("Whisper executable not found")
        print("   [FAIL] NOT FOUND")
        if env_whisper_path:
            print(f"   Path from .env: {env_whisper_path} (not found)")
        print("   Also searched in:")
        for path in whisper_paths:
            print(f"     - {path.absolute()}")
    print()
    
    # Check 2: Model file
    print("2. Checking for GGML model file...")
    model_paths = [
        Path("models/ggml-small.bin"),
        Path("models/ggml-tiny.bin"),
        Path("models/ggml-medium.bin"),
        Path("models/ggml-base.bin"),
        Path("ggml-small.bin"),
    ]
    
    model_found = None
    for path in model_paths:
        if path.exists():
            model_found = path
            size_mb = path.stat().st_size / (1024 * 1024)
            print(f"   [OK] Found: {path.absolute()} ({size_mb:.1f} MB)")
            break
    
    if not model_found:
        issues.append("GGML model file not found")
        print("   [FAIL] NOT FOUND")
        print("   Searched in:")
        for path in model_paths:
            print(f"     - {path.absolute()}")
    print()
    
    # Check 3: Models directory
    print("3. Checking models directory...")
    models_dir = Path("models")
    if models_dir.exists():
        print(f"   [OK] Directory exists: {models_dir.absolute()}")
        files = list(models_dir.glob("*.bin"))
        if files:
            print(f"   Found {len(files)} model file(s):")
            for f in files:
                size_mb = f.stat().st_size / (1024 * 1024)
                print(f"     - {f.name} ({size_mb:.1f} MB)")
        else:
            warnings.append("models/ directory is empty")
            print("   [WARN] Directory is empty")
    else:
        warnings.append("models/ directory does not exist")
        print("   [WARN] Directory does not exist")
        print(f"   Run: mkdir {models_dir.absolute()}")
    print()
    
    # Check 4: .env file
    print("4. Checking .env configuration...")
    env_file = Path(".env")
    if env_file.exists():
        print(f"   [OK] Found: {env_file.absolute()}")
        content = env_file.read_text()
        if "MATE_WHISPER" in content:
            print("   [OK] Contains MATE_WHISPER settings")
            for line in content.split('\n'):
                if line.strip().startswith('MATE_WHISPER'):
                    print(f"     {line}")
        else:
            warnings.append(".env exists but has no MATE_WHISPER settings")
            print("   [WARN] No MATE_WHISPER settings found")
    else:
        warnings.append(".env file not found")
        print("   [WARN] NOT FOUND")
        print("   Create .env with:")
        print("     MATE_WHISPER_EXECUTABLE=whisper.exe")
        print("     MATE_WHISPER_MODEL=models/ggml-small.bin")
        print('     MATE_WHISPER_DEVICE="CABLE Output (VB-Audio Virtual Cable)"')
        print("     MATE_CAPTION_ENGINE=whisper")
    print()
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if not issues and not warnings:
        print("[SUCCESS] ALL CHECKS PASSED!")
        print()
        print("You can now run the app:")
        print("  poetry run mate")
        return 0
    
    if issues:
        print(f"[FAIL] {len(issues)} CRITICAL ISSUE(S) FOUND:")
        for issue in issues:
            print(f"  - {issue}")
        print()
    
    if warnings:
        print(f"[WARN] {len(warnings)} WARNING(S):")
        for warning in warnings:
            print(f"  - {warning}")
        print()
    
    if issues:
        print("SETUP REQUIRED:")
        print()
        print("1. Download whisper.cpp:")
        print("   https://github.com/ggerganov/whisper.cpp/releases")
        print("   Place whisper.exe in project root")
        print()
        print("2. Download a GGML model:")
        print("   https://huggingface.co/ggerganov/whisper.cpp")
        print("   Recommended: ggml-small.bin")
        print("   Place in models/ directory")
        print()
        print("3. Create .env file with configuration (see above)")
        print()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(check_whisper_setup())

