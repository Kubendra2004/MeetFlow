import os
import winreg

# Get script's own folder and find the bat path dynamically
base_dir = os.path.dirname(os.path.abspath(__file__))
bat_path = os.path.join(base_dir, "startup_meetflow.bat")
key_name = "MeetFlow"

# Method 1: Windows Registry Run key (runs on every login, no admin needed)
try:
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_SET_VALUE
    )
    winreg.SetValueEx(key, key_name, 0, winreg.REG_SZ, f'"{bat_path}"')
    winreg.CloseKey(key)
    print(f"✅ MeetFlow added to Windows startup registry!")
    print(f"   Key: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\{key_name}")
    print(f"   Runs: {bat_path}")
    print()
    print("MeetFlow will now auto-start every time you log into Windows.")
    print("To remove: run remove_from_startup.py")
except Exception as e:
    print(f"❌ Failed to add to registry: {e}")

    # Method 2: Startup folder shortcut (fallback)
    try:
        import subprocess
        startup_dir = os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup")
        shortcut_path = os.path.join(startup_dir, "MeetFlow.bat")
        # Just copy the bat file reference into startup folder
        with open(shortcut_path, "w") as f:
            f.write(f'@echo off\ncall "{bat_path}"\n')
        print(f"✅ Fallback: Added to Startup folder: {shortcut_path}")
    except Exception as e2:
        print(f"❌ Fallback also failed: {e2}")
