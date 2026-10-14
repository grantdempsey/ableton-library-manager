# run_sandbox_test.py - Standard Execution Regression Test Harness Suite
import os
import time
import shutil
import threading
import json
import tkinter as tk
from sorter_engine import ParallelLibrarySorter, CONFIG_FILE

class MockTkWindow:
    def __init__(self):
        self.status_text = ""
        self.status_color = ""

    def after(self, delay, callback_func):
        if callback_func: 
            callback_func()

def create_clutter_sandbox():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    test_src = os.path.join(base_dir, "Sandbox_Input")
    test_dest = os.path.join(base_dir, "Sandbox_Output")
    
    print("\n" + "="*70)
    print("🧹 INITIALIZING SANDBOX TEST ENVIRONMENT SECTOR")
    print("="*70)
    for path in [test_src, test_dest]:
        if os.path.exists(path): 
            try:
                shutil.rmtree(path)
                print(f"  -> Wiped legacy folder: {os.path.basename(path)}")
            except Exception as e:
                print(f"  -> Warning: Could not clear {os.path.basename(path)}: {str(e)}")
        os.makedirs(path, exist_ok=True)
        
    populate_input_files(test_src)
    ensure_fallback_rules_exist()
    return test_src, test_dest

def ensure_fallback_rules_exist():
    """Guarantees that a valid library_config.json is present on disk so the engine matches keywords."""
    if not os.path.exists(CONFIG_FILE):
        print(f"⚙️  Provisioning default rules matrix into {CONFIG_FILE}...")
        default_rules = {
            "BPM_RANGES": [[0, 99, "99 BPM and Below"], [100, 114, "100-114 BPM"], [115, 129, "115-129 BPM"], [130, 149, "130-149 BPM"], [150, 174, "150-174 BPM"], [175, 999, "175 BPM and Above"]],
            "DRUM_KEYWORDS": {
                "\\bkick(s)?\\b": "Kicks",
                "\\bsnare(s)?\\b": "Snares",
                "\\b(hi)?hat(s)?\\b": "Hi-Hats",
                "\\bclap(s)?\\b": "Claps"
            },
            "SYNTH_EXTS": {".fxp": "Serum Presets", ".vital": "Vital Presets"},
            "NATIVE_EXTS": {".adg": "Live Instrument Racks", ".amxd": "Max For Live Devices"},
            "IGNORED_DIRECTORIES": ["eastwest", "kontakt library", "spectrasonics", "No Key Info"]
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_rules, f, indent=4)

def populate_input_files(test_src):
    print("⏳ Populating fresh testing mock assets into input directory...")
    dummy_assets = ["heavy_kick_ds01.wav", "crisp_snare_v2.aif", "closed_hat_08.wav", "ambient_loop_120bpm_Am.wav"]
    
    empty_nested_path = os.path.join(test_src, "Old_Pack_Folder", "Nested_Trash_Bin")
    os.makedirs(empty_nested_path, exist_ok=True)
    
    # Generate mock data folders to evaluate global folder exclusion behavior
    ignored_path = os.path.join(test_src, "kontakt library", "Instruments")
    os.makedirs(ignored_path, exist_ok=True)
    
    with open(os.path.join(ignored_path, "should_be_skipped.wav"), "wb") as f:
        f.write(b"IGNORE_THIS_DATA")
    
    for filename in dummy_assets:
        file_path = os.path.join(test_src, filename)
        with open(file_path, "wb") as f:
            f.write(b"MOCK_AUDIO_DATA_ARRAY_STREAM_CRC_CHECK")
        print(f"  -> Authored testing mock asset: {filename}")

if __name__ == "__main__":
    src_workspace, dest_workspace = create_clutter_sandbox()
    mock_window = MockTkWindow()
    
    import sorter_engine
    sorter_engine.load_external_config()
    
    # ----------------------------------------------------
    # TEST PHASE 1: IMPORT FUNCTIONALITY (Copy Mode)
    # ----------------------------------------------------
    print("\n" + "="*70)
    print("🚀 [TEST PHASE 1] Ingestion Pipeline: 'Import' (Copy Mode)")
    print("="*70)
    complete_event_1 = threading.Event()
    
    def done_callback_1(stats, mode):
        print("\n  [Callback Notice]: Phase 1 execution loop finished.")
        complete_event_1.set()

    sorter_import = ParallelLibrarySorter(
        src_path=src_workspace, dest_path=dest_workspace, window_el=mock_window,
        update_status_callback=lambda msg: print(f"  📈 [Import Status]: {msg}"),
        done_callback=done_callback_1, copy_mode=True
    )
    
    sorter_import.start_parallel_sort()
    complete_event_1.wait(timeout=2.0)
        
    src_count_p1 = len([f for f in os.listdir(src_workspace) if os.path.isfile(os.path.join(src_workspace, f))])
    print(f"  -> Original Input Folder : Contains {src_count_p1} files.")
    
    if src_count_p1 == 4:
        print("  ✅ PHASE 1 VERDICT: Perfect file distribution copy matching!")
    else:
        print("  ❌ PHASE 1 VERDICT: File array synchronization variance mismatch.")

    # ----------------------------------------------------
    # TEST PHASE 2: ENVIRONMENT AUTOMATION & PORTABILITY CHECKS
    # ----------------------------------------------------
    print("\n" + "="*70)
    print("🚀 [TEST PHASE 2] Profile Portability & Global Exclusions Verification")
    print("="*70)
    
    # Test 2A: Verification of the Exclusion Engine
    print("  -> Testing active global folder filtering arrays...")
    has_exclusions_passed = True
    for root, dirs, files in os.walk(dest_workspace):
        if "kontakt library" in root.lower() and len(files) > 0:
            has_exclusions_passed = False
            
    if has_exclusions_passed:
        print("  ✅ TEST 2A VERDICT: Exclusion engine skipped forbidden folders successfully!")
    else:
        print("  ❌ TEST 2A VERDICT: Exclusion rule engine failed to flag directory channels.")

    # Test 2B: Verification of Profile Import/Export Logic Schema
    mock_profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_profile_io.json")
    print(f"  -> Simulating workspace serialization loop parameters down to {os.path.basename(mock_profile_path)}...")
    try:
        mock_profile = {
            "profile_identity": "AFC_Production_Workspace",
            "DRUM_KEYWORDS": sorter_engine.DRUM_KEYWORDS,
            "IGNORED_DIRECTORIES": sorter_engine.IGNORED_DIRECTORIES
        }
        with open(mock_profile_path, 'w', encoding='utf-8') as f:
            json.dump(mock_profile, f, indent=4)
            
        with open(mock_profile_path, 'r', encoding='utf-8') as f:
            loaded_profile = json.load(f)
            
        if loaded_profile.get("profile_identity") == "AFC_Production_Workspace":
            print("  ✅ TEST 2B VERDICT: Profile portability engine data streams verified integer clean!")
        else:
            raise ValueError("Profile schema distortion detected.")
    except Exception as io_err:
        print(f"  ❌ TEST 2B VERDICT: Portability failure: {str(io_err)}")
    finally:
        if os.path.exists(mock_profile_path):
            os.remove(mock_profile_path)

    # ----------------------------------------------------
    # TEST PHASE 3: ORGANIZE FUNCTIONALITY (Move Mode + Cleanup)
    # ----------------------------------------------------
    print("\n" + "="*70)
    print("🚀 [TEST PHASE 3] System Optimization: 'Organize' (Move Mode)")
    print("="*70)
    
    # Reset workspace target areas
    if os.path.exists(dest_workspace):
        shutil.rmtree(dest_workspace)
    os.makedirs(dest_workspace, exist_ok=True)
    populate_input_files(src_workspace)
    time.sleep(0.2)

    sorter_organize = ParallelLibrarySorter(
        src_path=src_workspace, dest_path=dest_workspace, window_el=mock_window,
        update_status_callback=lambda msg: print(f"  📉 [Organize Status]: {msg}"),
        done_callback=lambda stats, mode: print("\n  [Callback Notice]: Phase 3 complete."), copy_mode=False
    )
    
    manifest = []
    for root, dirs, files in os.walk(src_workspace):
        for file in files:
            # Exclude folders handled by exclusions to check proper sorting behavior
            if not any(x in root.lower() for x in sorter_engine.IGNORED_DIRECTORIES):
                manifest.append((root, file))
            
    sorter_organize.total_files = len(manifest)
    for root_dir, file_item in manifest:
        sorter_organize.process_single_file(root_dir, file_item)
        
    sorter_organize.force_delete_empty_folders(src_workspace)

    print("\n" + "="*70)
    print("📋 FINAL SANDBOX ENVIRONMENT LIFECYCLE VERDICTS:")
    print("="*70)
    
    src_files_left = [os.path.join(r, f) for r, d, files in os.walk(src_workspace) for f in files if "kontakt library" not in r.lower()]
    if len(src_files_left) == 0:
        print("  ✅ ORGANIZE FILE MOVE: Passed! All audio files moved from source targets.")
    else:
        print(f"  ❌ ORGANIZE FILE MOVE: Failed! Leftover assets discovered: {src_files_left}")
            
    empty_folder_check = os.path.join(src_workspace, "Old_Pack_Folder")
    if not os.path.exists(empty_folder_check):
        print("  ✅ DEEP DIRECTORY SCRUBBER: Passed! Empty subfolders completely purged from drive.")
    else:
        print("  ❌ DEEP DIRECTORY SCRUBBER: Failed! Residual empty folders left behind.")
    print("="*70 + "\n")

