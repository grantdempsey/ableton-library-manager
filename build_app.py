# build_app.py - Insulated Standalone Compilation Suite
import os
import sys
import shutil
import subprocess

def terminate_orphaned_application_handles():
    """Locates and terminates stale background application handles to resolve process memory locks."""
    print("🧹 Cleaning environment memory spaces...")
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "AbletonLibraryManager.exe", "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print("  -> Terminated active background application process locks safely.")
        except Exception:
            pass

def clean_legacy_build_artifacts():
    """Wipes old tracking arrays and distribution folders to maintain a clean build workspace."""
    base_directory = os.path.dirname(os.path.abspath(__file__))
    garbage_targets = [
        os.path.join(base_directory, "build"),
        os.path.join(base_directory, "dist"),
        os.path.join(base_directory, "AbletonLibraryManager.spec")
    ]
    
    for target_path in garbage_targets:
        if os.path.exists(target_path):
            try:
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path)
                else:
                    os.remove(target_path)
                print(f"  -> Successfully wiped legacy artifact: {os.path.basename(target_path)}")
            except Exception as err:
                print(f"  -> Warning: Could not clear legacy asset {os.path.basename(target_path)}: {str(err)}")

def run_production_compiler_pipeline():
    """Initializes PyInstaller with explicit interpreter parameters to bypass environment path blocks."""
    print("\n" + "="*75)
    print("🚀 LAUNCHING ABLETON STUDIO MANAGER STANDALONE COMPILATION SUITE")
    print("="*75)
    
    terminate_orphaned_application_handles()
    clean_legacy_build_artifacts()
    
    script_entry = "AbletonLibraryManager.pyw"
    
    if not os.path.exists(script_entry):
        print(f"❌ Error: Script Entrypoint '{script_entry}' not found in current directory.")
        sys.exit(1)

    # 🌟 MAXIMUM COMPATIBILITY PYINSTALLER COMMAND ARRAY:
    pyinstaller_command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name=AbletonLibraryManager",
        
        # Explicitly collect tracking dependencies to prevent thread pool generation errors
        "--hidden-import=concurrent.futures",
        "--hidden-import=concurrent.futures.thread",
        "--hidden-import=stat",
        "--hidden-import=zipfile",
        "--hidden-import=datetime",
        "--hidden-import=subprocess",
        "--hidden-import=json",
        "--hidden-import=re",
        "--add-data=README.md;.",
        
        script_entry
    ]
    
    print("\nExecuting PyInstaller deployment strings across code tracks...")
    try:
        result = subprocess.run(pyinstaller_command, check=True)
        if result.returncode == 0:
            print("\n" + "="*75)
            print("🎉 SUCCESS: Standalone Studio Production Binary Built Flawlessly!")
            print(f"Target Output Folder: {os.path.abspath('dist/AbletonLibraryManager')}")
            print("="*75 + "\n")
    except subprocess.CalledProcessError as compile_err:
        print(f"\n❌ Compilation Pipeline Aborted: PyInstaller encountered a fatal error: {str(compile_err)}")
        sys.exit(1)

if __name__ == "__main__":
    run_production_compiler_pipeline()
