# audit_mac_safety.py - Block-Aware Multi-Platform Compliance Linter
import os
import re

CRITICAL_PATTERNS = {
    "OS_STARTFILE_CRASH": (
        r"os\.startfile\b",
        "🚨 FATAL: 'os.startfile' is a Windows-only binary hook. It will crash on macOS with a NameError."
    ),
    "UNSAFE_SHELL_SPAWN": (
        r"shell\s*=\s*True",
        "⚠️ WARNING: 'shell=True' invokes cmd.exe on Windows but /bin/sh on Mac."
    ),
    "HARDCODED_DRIVE_LETTER": (
        r"['\"][A-Za-z]:[/\\]",
        "📂 ROUTING FAULT: Hardcoded Windows absolute drive letter paths detected."
    ),
    "WIN32_FILE_ATTR_CRASH": (
        r"\.st_file_attributes\b",
        "🚨 FATAL: Native Win32 file attribute query parameters do not exist on Unix kernels."
    ),
    "UNSHIELDED_BACKSLASH": (
        r"\\.split\(['\"]\\\\['\"]\)",
        "⚙️ COHERENCE RISK: Parsing directory splits with literal backslashes breaks layouts on Mac."
    )
}

OPTIONAL_PATTERNS = {
    "MISSING_MACOS_STUB_FILTER": (
        r"if\s+.*\.startswith\(['\"]\._['\"]\)",
        "ℹ️ CAUTION: Ensure this directory scanner actively ignores hidden '._' AppleDouble fork stubs."
    )
}

def is_line_safely_shielded(source_lines, current_index):
    """Looks backward through the block hierarchy to detect active cross-platform shield logic."""
    # Scan up to 5 lines backwards to verify indentation block safety structures
    start_lookback = max(0, current_index - 5)
    for check_idx in range(current_index - 1, start_lookback - 1, -1):
        parent_line = source_lines[check_idx]
        
        # Verify if a platform check or attribute guard shields this block
        if "platform.system()" in parent_line or "CURRENT_OS" in parent_line or "hasattr(" in parent_line:
            # Only trigger a skip if it's explicitly targeting a Windows check structure
            if "Windows" in parent_line or "hasattr" in parent_line:
                return True
    return False

def execute_workspace_audit():
    """Explores the active local workspace hierarchy to flag unshielded cross-platform bugs."""
    print("=" * 85)
    print("🎹 ABLETON STUDIO MANAGER - CROSS-PLATFORM SYSTEM COMPLIANCE REPORT")
    print("=" * 85)
    
    root_dir = os.path.dirname(os.path.abspath(__file__))
    analyzed_files_count = 0
    total_violations_found = 0
    
    for current_dir, _, file_list in os.walk(root_dir):
        if any(ignored in current_dir.lower() for ignored in ["venv", ".git", "__pycache__", "build", "dist"]):
            continue
            
        for file_name in file_list:
            if not file_name.endswith(('.py', '.pyw')) or file_name == "audit_mac_safety.py":
                continue
                
            analyzed_files_count += 1
            full_path = os.path.join(current_dir, file_name)
            relative_display_path = os.path.relpath(full_path, root_dir)
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    source_lines = f.readlines()
            except Exception as e:
                print(f" [Read Failure]: Could not open {relative_display_path} -> {str(e)}")
                continue
                
            file_reported_header = False
            
            for index, line_content in enumerate(source_lines):
                clean_line = line_content.strip()
                if clean_line.startswith("#") or not clean_line:
                    continue
                
                # Check for protective guards on the line itself or within its parent indentation block
                if is_line_safely_shielded(source_lines, index):
                    continue
                    
                for vulnerability_id, (regex_pattern, hazard_message) in {**CRITICAL_PATTERNS, **OPTIONAL_PATTERNS}.items():
                    if re.search(regex_pattern, line_content):
                        if not file_reported_header:
                            print(f"\n📂 File: {relative_display_path}")
                            print("-" * 50)
                            file_reported_header = True
                            
                        marker = "🟥" if "CRASH" in vulnerability_id or "FAULT" in vulnerability_id else "🟨"
                        print(f"  [{marker} Line {index + 1}]: {clean_line}")
                        print(f"    ℹ️ {hazard_message}\n")
                        total_violations_found += 1

    print("=" * 85)
    print(f"🎯 AUDIT OVERVIEW: Evaluated {analyzed_files_count} project files. Found {total_violations_found} cross-platform line adjustments.")
    print("=" * 85)

if __name__ == "__main__":
    execute_workspace_audit()
