# Bring the agent's StealthWriter window to the front and reload it, so no
# result from a previous run is left on the page. Run before every humanize_blocks.
Add-Type @"
using System; using System.Runtime.InteropServices;
public class SWP { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c); [DllImport("user32.dll")] public static extern void keybd_event(byte b,byte s,uint f,UIntPtr e);}
"@
for ($try = 1; $try -le 8; $try++) {
    # The agent's browser is Playwright's Chromium; find it by path (its title is
    # briefly empty while a page loads).
    $p = Get-Process chrome -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 -and $_.Path -like "*ms-playwright*" } |
        Select-Object -First 1
    if ($p) {
        [SWP]::keybd_event(0x12,0,0,[UIntPtr]::Zero); [SWP]::keybd_event(0x12,0,2,[UIntPtr]::Zero)
        [SWP]::ShowWindow($p.MainWindowHandle,9) | Out-Null
        [SWP]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 500
        $p.Refresh()
        if ($p.MainWindowTitle -like "*StealthWriter*") {
            (New-Object -ComObject WScript.Shell).SendKeys("{F5}")
            Start-Sleep -Seconds 5
            "RELOADED: $($p.MainWindowTitle)"
            exit 0
        }
    }
    Start-Sleep -Seconds 1
}
if ($p) { "FRONT_ONLY (active tab is not StealthWriter): '$($p.MainWindowTitle)'" } else { "NO_WINDOW" }
