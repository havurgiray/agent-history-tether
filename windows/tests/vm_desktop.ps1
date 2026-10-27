# aht on a Windows desktop: the tray, its menu, aht's window, the welcome,
# the folder picker (a folder chosen in it, Cancel, a path pasted into its
# Folder: field), Continue's console, notices,
# Show in Explorer and start at login (and the watcher alone, as the logon
# entry starts it), each checked and screenshot, and that Windows Security
# found nothing.  Run by vm_check.sh through a scheduled task that runs in
# the logged-on session (ssh's own session has no desktop).  Everything uses
# a throwaway aht home with a made-up project; `claude` is a stand-in.  The
# machine's own tray and watcher, if they run, stop first (one of each runs
# per sign-in: the check's would give way to them) and start again at the
# end; the HKCU Run entry is put back as it was.
# Results: results.jsonl and PNGs in $Out.  Keep this file UTF-8 with a
# BOM: Windows PowerShell 5 reads a file without one as cp1252.
param([string]$Root = "$env:USERPROFILE\aht-check")

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$Out = "$Root\out"
New-Item -ItemType Directory -Force $Out | Out-Null
Add-Type -AssemblyName System.Windows.Forms, System.Drawing, UIAutomationClient, UIAutomationTypes, WindowsBase, System.Net.Http
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class W {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string c, string t);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode, EntryPoint="SendMessageW")] public static extern IntPtr SendText(IntPtr h, uint m, IntPtr w, string l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode, EntryPoint="SendMessageW")] public static extern IntPtr ReadText(IntPtr h, uint m, IntPtr w, System.Text.StringBuilder l);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder b, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder b, int n);
  public static string Front(bool cls) {
    var b = new System.Text.StringBuilder(256); var h = GetForegroundWindow();
    if (cls) GetClassName(h, b, 256); else GetWindowText(h, b, 256);
    return b.ToString();
  }
  public static void Raise(IntPtr h) {   // an Alt tap lets this process hand the foreground over
    keybd_event(0x12, 0, 0, UIntPtr.Zero); SetForegroundWindow(h); keybd_event(0x12, 0, 2, UIntPtr.Zero);
  }
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowEx(IntPtr p, IntPtr after, string c, string t);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int a, out int v, int n);
  [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint f);
  public static IntPtr RootAt(int x, int y) {   // the top-level window at a point of the screen
    var p = new POINT(); p.X = x; p.Y = y; return GetAncestor(WindowFromPoint(p), 2);
  }
  public static IntPtr[] Shown(string cls) {   // the top-level windows of a class that are on screen
    var l = new System.Collections.Generic.List<IntPtr>(); var h = IntPtr.Zero; int c;
    while ((h = FindWindowEx(IntPtr.Zero, h, cls, null)) != IntPtr.Zero)
      if (IsWindowVisible(h) && (DwmGetWindowAttribute(h, 14, out c, 4) != 0 || c == 0)) l.Add(h);   // not cloaked
    var f = GetForegroundWindow(); var b = new System.Text.StringBuilder(256); GetClassName(f, b, 256);
    if (b.ToString() == cls && !l.Contains(f)) l.Add(f);
    return l.ToArray();
  }
  // the display stays on while the check runs (ES_CONTINUOUS | ES_DISPLAY_REQUIRED |
  // ES_SYSTEM_REQUIRED); Wake also turns it on now: a mouse move of 0 counts as use
  public static void Awake() { SetThreadExecutionState(0x80000003); }
  public static void Wake() { Awake(); mouse_event(1, 0, 0, 0, UIntPtr.Zero); }
  public static void Rest() { SetThreadExecutionState(0x80000000); }
}
// the folder chooser's tree, a SysTreeView32 of another process (UI Automation
// sees no items in it): its items, and an item's text and where its label is
// on the screen, read through a buffer in that process (64-bit ones only)
public static class TV {
  [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr h, ref W.POINT p);
  [DllImport("user32.dll")] static extern uint GetDpiForWindow(IntPtr h);
  [DllImport("user32.dll")] static extern uint GetDpiForSystem();
  [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(uint a, bool i, uint pid);
  [DllImport("kernel32.dll")] static extern IntPtr VirtualAllocEx(IntPtr p, IntPtr a, IntPtr n, uint t, uint pr);
  [DllImport("kernel32.dll")] static extern bool VirtualFreeEx(IntPtr p, IntPtr a, IntPtr n, uint t);
  [DllImport("kernel32.dll")] static extern bool WriteProcessMemory(IntPtr p, IntPtr a, byte[] b, IntPtr n, out IntPtr w);
  [DllImport("kernel32.dll")] static extern bool ReadProcessMemory(IntPtr p, IntPtr a, byte[] b, IntPtr n, out IntPtr r);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  public static IntPtr Next(IntPtr tv, int code, IntPtr item) { return SendMessage(tv, 0x110A, (IntPtr)code, item); }   // TVM_GETNEXTITEM
  public static void Show(IntPtr tv, IntPtr item) { SendMessage(tv, 0x1114, IntPtr.Zero, item); }   // TVM_ENSUREVISIBLE
  public static string Text(IntPtr tv, IntPtr item, int[] at) {   // at: the middle of its label
    uint pid; GetWindowThreadProcessId(tv, out pid);
    IntPtr p = OpenProcess(0x38, false, pid), n;          // PROCESS_VM_OPERATION | _READ | _WRITE
    if (p == IntPtr.Zero || IntPtr.Size != 8) return null;
    IntPtr buf = VirtualAllocEx(p, IntPtr.Zero, (IntPtr)4096, 0x3000, 4);
    try {
      var it = new byte[56];                              // TVITEMW: mask, hItem, pszText, cchTextMax
      BitConverter.GetBytes(1).CopyTo(it, 0);             // TVIF_TEXT
      BitConverter.GetBytes(item.ToInt64()).CopyTo(it, 8);
      BitConverter.GetBytes(buf.ToInt64() + 1024).CopyTo(it, 24);
      BitConverter.GetBytes(260).CopyTo(it, 32);
      WriteProcessMemory(p, buf, it, (IntPtr)it.Length, out n);
      if (SendMessage(tv, 0x113E, IntPtr.Zero, buf) == IntPtr.Zero) return null;   // TVM_GETITEMW
      var t = new byte[520];
      ReadProcessMemory(p, IntPtr.Add(buf, 1024), t, (IntPtr)t.Length, out n);
      var s = System.Text.Encoding.Unicode.GetString(t);
      s = s.Substring(0, Math.Max(0, s.IndexOf((char)0)));
      if (at != null) {                                   // TVM_GETITEMRECT: the item in, its label out
        WriteProcessMemory(p, IntPtr.Add(buf, 2048), BitConverter.GetBytes(item.ToInt64()), (IntPtr)8, out n);
        if (SendMessage(tv, 0x1104, (IntPtr)1, IntPtr.Add(buf, 2048)) == IntPtr.Zero) return null;
        var r = new byte[16];
        ReadProcessMemory(p, IntPtr.Add(buf, 2048), r, (IntPtr)r.Length, out n);
        // a tree that is not DPI aware counts in 96-dpi units: the screen's are larger
        double k = (double)GetDpiForSystem() / Math.Max(96u, GetDpiForWindow(tv));
        var o = new W.POINT(); ClientToScreen(tv, ref o);
        at[0] = o.X + (int)((BitConverter.ToInt32(r, 0) + BitConverter.ToInt32(r, 8)) / 2 * k);
        at[1] = o.Y + (int)((BitConverter.ToInt32(r, 4) + BitConverter.ToInt32(r, 12)) / 2 * k);
      }
      return s;
    } finally { VirtualFreeEx(p, buf, IntPtr.Zero, 0x8000); CloseHandle(p); }
  }
}
"@
[W]::SetProcessDPIAware() | Out-Null
# a display that sleeps while nobody uses the machine gives screenshots of its
# last frame, from before it slept
[W]::Wake(); Start-Sleep 1
$UIA = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]

function Shot($name) {
  [W]::Awake()                 # no mouse move here: it could pick an item of the tray's menu
  $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
  $bmp.Save("$Out\$name.png", [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  return "$name.png"
}
function Result($check, $ok, $detail, $shot) {
  $o = [ordered]@{ check = $check; ok = $ok; detail = "$detail"; shot = $shot }
  Add-Content -Encoding UTF8 "$Out\results.jsonl" ($o | ConvertTo-Json -Compress)
}
function Windows($name) {      # top-level windows whose title is $name
  $c = New-Object System.Windows.Automation.PropertyCondition($UIA::NameProperty, $name)
  return @($UIA::RootElement.FindAll($TS::Children, $c))
}
function WindowsLike($start) {  # top-level windows whose title begins with $start
  return @($UIA::RootElement.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition) |
    Where-Object { $_.Current.Name -like "$start*" })
}
function Like($root, $part) {
  foreach ($e in $root.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
    if ($e.Current.Name -like "*$part*") { return $e }
  }
  return $null
}
function Keys($k) { [System.Windows.Forms.SendKeys]::SendWait($k) }
function ClickAt($x, $y) {
  [W]::SetCursorPos($x, $y) | Out-Null; Start-Sleep -Milliseconds 300
  [W]::mouse_event(2, 0, 0, 0, [UIntPtr]::Zero); [W]::mouse_event(4, 0, 0, 0, [UIntPtr]::Zero)
}
function InRoot($path) { return [bool]$path -and $path.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase) }
function Ours { # the aht processes of this check (its own exes), never the machine's own aht
  Get-CimInstance Win32_Process -Filter "name='aht.exe' or name='aht-tray.exe'" |
    Where-Object { InRoot $_.ExecutablePath }
}
function Consoles { # the consoles Continue opened: they run the check's stand-in claude
  Get-CimInstance Win32_Process -Filter "name='cmd.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf("$Box\claude.cmd", [StringComparison]::OrdinalIgnoreCase) -ge 0 }
}
function Toasts { # the Dismiss buttons of the notices on screen: UIA sees a toast only from its window
  $id = New-Object System.Windows.Automation.PropertyCondition($UIA::AutomationIdProperty, "DismissButton")
  foreach ($h in [W]::Shown("Windows.UI.Core.CoreWindow")) {
    try { $UIA::FromHandle($h).FindAll($TS::Descendants, $id) } catch {}
  }
}
function Buttons($w) {  # the named buttons in a window (for Edge: those of its page)
  return @($w.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition) |
    Where-Object { $_.Current.ControlType.ProgrammaticName -eq "ControlType.Button" -and $_.Current.Name })
}
function WaitButton($hw, $like, $secs) {  # an enabled button like $like in the window, once it is there
  for ($i = 0; $i -lt $secs; $i++) {
    $b = Buttons ($UIA::FromHandle($hw)) | Where-Object { $_.Current.Name -like $like -and $_.Current.IsEnabled } | Select-Object -First 1
    if ($b) { return $b }
    Start-Sleep 1
  }
  return $null
}
function ClickOn($hw, $e, $like) {  # a real click on the element $e of the window $hw, only when
  # that window is in front and $e (named like $like) is what is under the point: "" when clicked, else why not
  $r = $e.Current.BoundingRectangle
  $x = [int]($r.X + $r.Width / 2); $y = [int]($r.Y + $r.Height / 2)
  if ([W]::GetForegroundWindow() -ne $hw) { return "the window was not in front (" + [W]::Front($false) + " was): no click" }
  if ([W]::RootAt($x, $y) -ne $hw) { return "another window was over '$like': no click" }
  $at = $UIA::FromPoint((New-Object System.Windows.Point($x, $y)))
  if ($at.Current.Name -notlike $like) { return "under the point was '" + $at.Current.Name + "', not '$like': no click" }
  ClickAt $x $y
  return ""
}
function RealClick($hw, $like) {  # a real click on a button of the window $hw (as ClickOn)
  $b = WaitButton $hw $like 10
  if (-not $b) { return "no button like '$like' in the window" }
  return ClickOn $hw $b $like
}
function Choosers($server) { # the folder choosers on screen that the window's server opened
  return @($UIA::RootElement.FindAll($TS::Children, [System.Windows.Automation.Condition]::TrueCondition) |
    Where-Object { $_.Current.ClassName -eq "#32770" -and
                   (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Current.ProcessId)").ParentProcessId -eq $server })
}
function ClearToasts { # dismiss the notices on screen: how many stay
  for ($i = 0; $i -lt 3; $i++) {
    $up = @(Toasts)
    if ($up.Count -eq 0) { return 0 }
    foreach ($e in $up) { try { $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() } catch {} }
    Start-Sleep 1
  }
  return @(Toasts).Count
}

# ---- the machine's own tray and watcher stop until the end: the tray and
# the watcher run once per sign-in, so the check's would give way to them ----
$Session = (Get-Process -Id $PID).SessionId
$Theirs = @(Get-CimInstance Win32_Process -Filter "name='aht.exe' or name='aht-tray.exe'" |
  Where-Object { $_.SessionId -eq $Session -and $_.ExecutablePath -and -not (InRoot $_.ExecutablePath) -and
                 ($_.Name -eq "aht-tray.exe" -or $_.CommandLine -match '\swatch(\s|$)') })
$Theirs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if ($Theirs) { Start-Sleep 2 }
$EnvBefore = @{}
Get-ChildItem env: | Where-Object { $_.Name -like "AHT_*" } | ForEach-Object { $EnvBefore[$_.Name] = $_.Value }

# ---- a throwaway aht home with one made-up project and session ----
$Dist = "$Root\windows\dist\aht"
$Box = "$Root\box"
Remove-Item -Recurse -Force $Box -ErrorAction SilentlyContinue
$Proj = "$Box\roots\demo-project"
New-Item -ItemType Directory -Force $Proj, "$Box\home\.aht", "$Box\tools\nope", "$Box\trash" | Out-Null
Set-Content "$Proj\README.md" "# demo project"
$env:AHT_HOME = "$Box\home\.aht"
$env:AHT_ROOTS = "$Box\roots"
$env:AHT_ROOT_CLAUDE = "$Box\tools\claude"
foreach ($b in "GEMINI", "CURSOR", "OPENCODE", "CODEX", "COPILOT", "KIMI", "KIMI_CODE") { Set-Item "env:AHT_ROOT_$b" "$Box\tools\nope" }
$env:AHT_NO_ICONS = "1"; $env:AHT_NO_BACKUP = "1"; $env:AHT_TRASH = "$Box\trash"
$enc = (& "$Dist\aht.exe" encode $Proj).Trim()
New-Item -ItemType Directory -Force "$Box\tools\claude\$enc" | Out-Null
$now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$j = $Proj.Replace("\", "\\")
@(
  '{"type":"user","cwd":"' + $j + '","timestamp":"' + $now + '","entrypoint":"cli","message":{"role":"user","content":"write a short README"}}',
  '{"type":"ai-title","aiTitle":"Write the README"}',
  '{"type":"assistant","cwd":"' + $j + '","timestamp":"' + $now + '","message":{"role":"assistant","content":[{"type":"text","text":"Done. Shall I add a licence too?"}]}}'
) | Set-Content -Encoding UTF8 "$Box\tools\claude\$enc\demo1-0000-4000-8000-000000000001.jsonl"
# Continue runs this instead of the real claude; it notes the folder it runs in
Set-Content -Encoding ASCII "$Box\claude.cmd" @("@echo aht check: claude %*", '@cd > "%~dp0continue-cwd.txt"')
$env:AHT_CLAUDE = "$Box\claude.cmd"
$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$Started = Get-Date
$runBefore = (Get-ItemProperty $RunKey -ErrorAction SilentlyContinue)."aht-watcher"

# ---- 1. the tray starts and stays up ----
$tray = Start-Process "$Dist\aht-tray.exe" -PassThru
Start-Sleep 6
$crash = Windows "Unhandled exception in script"
$alive = -not $tray.HasExited
Result "tray starts" ($alive -and -not $crash) ("pid " + $tray.Id + $(if ($crash) { ", an error dialog" } else { "" })) (Shot "01-tray")

# ---- 2. its menu: Open aht… opens the window ----
$ahtOld = @(Windows "aht" | ForEach-Object { $_.Current.NativeWindowHandle })
$before = $ahtOld.Count
$h = [W]::FindWindow("aht_tray_wnd", "aht-tray")
[W]::Raise($h)                             # else the menu may show without the keyboard
[W]::PostMessage($h, 0x8001, [IntPtr]::Zero, [IntPtr]0x202) | Out-Null   # a click on the icon
Start-Sleep 2
$menuShot = Shot "02-menu"
# keys only into the menu, never another window: while it shows, its owner
# (the tray's window) is the foreground window
$front = [W]::Front($true)
$menuUp = $front -in "aht_tray_wnd", "#32768"
if ($menuUp) {
  Keys "{DOWN}{DOWN}{DOWN}"                # past the two status lines: Open aht…
  Start-Sleep -Milliseconds 500
  Keys "{ENTER}"
  $detail = "aht windows: $before before"
} else {
  $detail = "the menu did not get the keyboard (" + [W]::Front($false) + " had it); no keys sent"
  [W]::PostMessage($h, 0x001F, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null   # WM_CANCELMODE: the menu goes
}
$opened = $false
for ($i = 0; $i -lt 20 -and -not $opened -and $menuUp; $i++) { Start-Sleep 1; $opened = (Windows "aht").Count -gt $before }
Result "tray menu → Open aht… → the window" $opened $detail (Shot "03-window")
if (-not $opened) {                        # the rest needs the window's server
  Start-Process "$Dist\aht.exe" -ArgumentList "window" -WindowStyle Hidden
  for ($i = 0; $i -lt 20 -and -not (Test-Path "$env:AHT_HOME\run\window.json"); $i++) { Start-Sleep 1 }
}

# ---- talk to the window's server as the page does ----
$st = Get-Content "$env:AHT_HOME\run\window.json" -Raw | ConvertFrom-Json
$base = "http://127.0.0.1:" + $st.port
$launch = Invoke-RestMethod -UseBasicParsing "$base/launch?control=$($st.control)"
# the launch link answers with the session's cookie and sends the page on to
# /#k=<key>: every API call carries both, the key in X-AHT.  The redirect is
# not followed, and the cookie is sent by hand (a handler that keeps cookies
# itself drops it)
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.UseCookies = $false
$handler.AllowAutoRedirect = $false
$http = New-Object System.Net.Http.HttpClient($handler)
$http.Timeout = [TimeSpan]::FromMinutes(10)
$open = $http.GetAsync($launch.url).Result
$set = if ($open.Headers.Contains("Set-Cookie")) { @($open.Headers.GetValues("Set-Cookie")) -join "; " } else { "" }
$cookie = if ($set -match '(?:^|[;,]\s*)aht=([^;]+)') { $Matches[1] } else { "" }
$loc = if ($open.Headers.Location) { $open.Headers.Location.OriginalString } else { "" }
$key = if ($loc -match '#k=([^&]+)') { [Uri]::UnescapeDataString($Matches[1]) } else { "" }
function Ask($path, $xaht) {   # a GET of the API: its status code
  $req = New-Object System.Net.Http.HttpRequestMessage ([System.Net.Http.HttpMethod]::Get), "$base$path"
  $req.Headers.Add("X-AHT", $xaht); $req.Headers.Add("Cookie", "aht=$cookie")
  return [int]$http.SendAsync($req).Result.StatusCode
}
$withKey = Ask "/api/ping" $key
$withOne = Ask "/api/ping" "1"
Result "the window's API wants the key of its session" ([int]$open.StatusCode -eq 302 -and $cookie -and $key -and $withKey -eq 200 -and $withOne -ge 400 -and $withOne -lt 500) ("open: " + [int]$open.StatusCode + ", with the key: $withKey, with 1: $withOne") $null
function Send($path, $body) {
  $req = New-Object System.Net.Http.HttpRequestMessage ([System.Net.Http.HttpMethod]::Post), "$base$path"
  $req.Headers.Add("X-AHT", $key); $req.Headers.Add("Cookie", "aht=$cookie")
  $req.Content = New-Object System.Net.Http.StringContent (($body | ConvertTo-Json -Compress -Depth 5), [Text.Encoding]::UTF8, "application/json")
  return $http.SendAsync($req)
}
function Api($path, $body) { return (Send $path $body).Result.Content.ReadAsStringAsync().Result | ConvertFrom-Json }
function Run([string[]]$cmd) { return Api "/api/run" @{ args = $cmd } }

# ---- 3. the welcome: setup, with the made-up project ----
$plan = (Run @("setup", "--json")).json
$found = @($plan.projects | Where-Object { $_.path -eq $Proj }).Count -eq 1
$done = (Run @("setup", "--apply", "--json", "--adopt", $Proj, "--update-check", "off")).json
Result "setup finds and takes on the project" ($found -and $done.adopted -contains $Proj) ("adopted: " + ($done.adopted -join ", ")) $null

# ---- 4. the folder picker comes up in front of the window, and the folder
# chosen in it reaches the page ----
# as a person meets it: a real click in the window (the welcome's Choose Each
# Step…, then Add Folder…) on a server that has run for a while.  Windows
# lets a process that has just started put a window in front until it has
# used that up; the server used it to open its browser window (as `aht
# window` does), and after about 100 s it has none left.  So only a chooser
# that brings itself to the front passes: it once opened behind the window.
$win = Windows "aht" | Where-Object { $_.Current.ClassName -eq "Chrome_WidgetWin_1" -and
                                      $ahtOld -notcontains $_.Current.NativeWindowHandle } | Select-Object -First 1
$why = ""; $chooser = $null; $front = ""; $age = 0
if (-not $win) { $why = "the window from step 2 is not there" } else {
  $hw = [IntPtr]$win.Current.NativeWindowHandle
  $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$st.started
  if ($age -lt 110) { Start-Sleep ([int][math]::Ceiling(110 - $age)) }
  $age = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$st.started)
  [W]::Wake(); $null = ClearToasts
  # Chromium shows its page to UI Automation only while nothing covers the
  # window: up with it first, then look for the buttons
  if ([W]::GetForegroundWindow() -ne $hw) { [W]::Raise($hw); Start-Sleep 2 }
  if (-not (WaitButton $hw "Choose Each Step*" 60)) { $why = "the welcome's Choose Each Step… is not in the window" }
  else { $why = RealClick $hw "Choose Each Step*" }
  if (-not $why) { Start-Sleep 1; $why = RealClick $hw "Add Folder*" }
  if (-not $why) {
    for ($i = 0; $i -lt 40 -and -not $chooser; $i++) { Start-Sleep -Milliseconds 500; $chooser = Choosers $st.pid | Select-Object -First 1 }
    if ($chooser) { Start-Sleep 2; $front = [W]::Front($true) + " " + [W]::Front($false) } else { $why = "no folder chooser came up" }
  }
}
$inFront = $chooser -and [W]::GetForegroundWindow() -eq [IntPtr]$chooser.Current.NativeWindowHandle
Result "the folder picker comes up in front after a click in the window" ([bool]$inFront) $(if ($why) { $why } else { "server $age s old; in front: $front" }) (Shot "04-folder-picker")

function AsShown($path) {      # a path as the page shows it
  if ($path.StartsWith("$env:USERPROFILE\", [StringComparison]::OrdinalIgnoreCase)) { return "~" + $path.Substring($env:USERPROFILE.Length) }
  return $path
}
function NoPrompt {            # $true when the page asks for a path as text; that prompt then goes
  if (-not (Like ($UIA::FromHandle($hw)) "Type or paste the folder*")) { return $false }
  $b = Buttons ($UIA::FromHandle($hw)) | Where-Object { $_.Current.Name -eq "Cancel" } | Select-Object -First 1
  if ($b) {
    $r = $b.Current.BoundingRectangle; $x = [int]($r.X + $r.Width / 2); $y = [int]($r.Y + $r.Height / 2)
    # UIA names no button at the point in the browser's prompt: the window there, then
    if ([W]::GetForegroundWindow() -eq $hw -and [W]::RootAt($x, $y) -eq $hw) { ClickAt $x $y; Start-Sleep 1 }
  }
  return $true
}
function NewChooser {          # the chooser the window's server brings up next, or $null
  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    $c = Choosers $st.pid | Select-Object -First 1
    if ($c) { Start-Sleep 2; return $c }
  }
  return $null
}
function ClickForChooser {     # a real click on the welcome's Add Folder…: the chooser it brings up, or why not
  if (-not $hw) { return "the window from step 2 is not there" }
  if ([W]::GetForegroundWindow() -ne $hw) { [W]::Raise($hw); Start-Sleep 2 }
  $why = RealClick $hw "Add Folder*"
  if ($why) { return $why }
  $c = NewChooser
  if ($c) { return $c }
  return "no folder chooser came up"
}
function Control($d, $prop, $value) {   # a control of the chooser $d
  return $d.FindFirst($TS::Descendants, (New-Object System.Windows.Automation.PropertyCondition($prop, $value)))
}
function Press($d, $id) {      # a real click on the chooser's OK (1) or Cancel (2) while it is in front: "" or why not
  $dh = [IntPtr]$d.Current.NativeWindowHandle
  $b = Control $d $UIA::AutomationIdProperty "$id"
  if ([W]::GetForegroundWindow() -ne $dh) { return "the chooser was not in front (" + [W]::Front($false) + " was): no click" }
  if (-not $b) { return "no button $id in the chooser" }
  return ClickOn $dh $b $b.Current.Name
}
function Listed($text) {       # the page shows $text, within 15 s
  if ([W]::GetForegroundWindow() -ne $hw) { [W]::Raise($hw); Start-Sleep 2 }   # the page shows itself to UIA in front
  for ($i = 0; $i -lt 15; $i++) { if (Like ($UIA::FromHandle($hw)) $text) { return $true }; Start-Sleep 1 }
  return $false
}

# the folder chosen in it reaches the page, as a person chooses one: a real
# click on Music in its tree, then on OK, each only while the chooser is in
# front and the point is on that item; the welcome then lists the folder
$music = [Environment]::GetFolderPath("MyMusic")
$want = if ($music) { AsShown $music } else { "" }
$listed = $false; $prompt = $false
if (-not $chooser) { $why = "no folder chooser" }
elseif (-not $music -or -not (Test-Path $music)) { $why = "this user has no Music folder" }
else {
  $dh = [IntPtr]$chooser.Current.NativeWindowHandle
  $d = $UIA::FromHandle($dh)
  $had = [bool](Like ($UIA::FromHandle($hw)) $want)
  $name = (New-Object -ComObject Shell.Application).NameSpace($music).Self.Name   # as the tree names it
  $tv = Control $d $UIA::ClassNameProperty "SysTreeView32"
  $tv = if ($tv) { [IntPtr]$tv.Current.NativeWindowHandle } else { [IntPtr]::Zero }
  $item = [TV]::Next($tv, 4, [TV]::Next($tv, 0, [IntPtr]::Zero))   # the first under the root (Desktop)
  while ($item -ne [IntPtr]::Zero -and [TV]::Text($tv, $item, $null) -ne $name) { $item = [TV]::Next($tv, 1, $item) }
  [int[]]$at = 0, 0
  if ($item -ne [IntPtr]::Zero) { [TV]::Show($tv, $item); Start-Sleep 1; $null = [TV]::Text($tv, $item, $at) }
  $pt = New-Object W+POINT; $pt.X = $at[0]; $pt.Y = $at[1]
  $why = if ($had) { "the welcome listed $want before" } elseif ($item -eq [IntPtr]::Zero) { "no '$name' in the chooser's tree" }
         elseif ([W]::GetForegroundWindow() -ne $dh) { "the chooser was not in front (" + [W]::Front($false) + " was): no click" }
         elseif ([W]::WindowFromPoint($pt) -ne $tv) { "the chooser's tree was not under '$name': no click" } else { "" }
  if (-not $why) {
    ClickAt $at[0] $at[1]; Start-Sleep 1
    $why = if ([TV]::Next($tv, 9, [IntPtr]::Zero) -ne $item) { "'$name' was clicked but is not chosen" }   # TVGN_CARET
           else { Press $d 1 }
  }
  if ($why) { [W]::PostMessage($dh, 0x0111, [IntPtr]2, [IntPtr]::Zero) | Out-Null }   # its Cancel
  Start-Sleep 2
  if (-not $why) { $listed = Listed $want }
}
$shot = Shot "04a-folder-chosen"
$prompt = $hw -and (NoPrompt)
Result "the folder chosen in the picker reaches the page" ($listed -and -not $prompt) $(if ($why) { $why } elseif ($prompt) { "the page asks for the path as text" } elseif ($listed) { "the welcome lists $want" } else { "the welcome does not list $want" }) $shot

# Cancel ends it: no second box (the page once asked for the path as text
# then), the chooser goes and the page goes on as before
$c = ClickForChooser
$why = if ($c -is [string]) { $c } else { Press $c 2 }
if ($why -and $c -isnot [string]) { [W]::PostMessage([IntPtr]$c.Current.NativeWindowHandle, 0x0111, [IntPtr]2, [IntPtr]::Zero) | Out-Null }
Start-Sleep 3
if ($hw -and [W]::GetForegroundWindow() -ne $hw) { [W]::Raise($hw); Start-Sleep 2 }
$left = @(Choosers $st.pid).Count
$usable = $hw -and (WaitButton $hw "Add Folder*" 5) -and -not (Like ($UIA::FromHandle($hw)) "waiting for a folder")
$shot = Shot "04c-folder-cancelled"
$prompt = $hw -and (NoPrompt)
Result "Cancel in the folder picker ends it: no second box" (-not $why -and -not $prompt -and $left -eq 0 -and $usable) $(if ($why) { $why } elseif ($prompt) { "the page asks for the path as text" } elseif ($left) { "$left chooser(s) still up" } elseif (-not $usable) { "the page does not go on (no Add Folder…, or still waiting)" } else { "nothing more is asked; the page goes on" }) $shot

# a path pasted into its Folder: field reaches the page: the text goes into
# that field by its handle (as a paste does), only while the chooser is in
# front, then a real click on OK
$paste = "$Box\pasted folder"
New-Item -ItemType Directory -Force $paste | Out-Null
$want = AsShown $paste
$listed = $false; $told = $false
$c = ClickForChooser
if ($c -is [string]) { $why = $c } else {
  $dh = [IntPtr]$c.Current.NativeWindowHandle
  $field = Control $c $UIA::ClassNameProperty "Edit"
  $why = if (-not $field) { "no Folder: field in the chooser" }
         elseif ([W]::GetForegroundWindow() -ne $dh) { "the chooser was not in front (" + [W]::Front($false) + " was): nothing put in" } else { "" }
  if (-not $why) {
    $eh = [IntPtr]$field.Current.NativeWindowHandle
    $got = New-Object System.Text.StringBuilder 1024
    [W]::SendText($eh, 0x000C, [IntPtr]::Zero, $paste) | Out-Null          # WM_SETTEXT
    [W]::ReadText($eh, 0x000D, [IntPtr]1024, $got) | Out-Null              # WM_GETTEXT
    $why = if ($got.ToString() -ne $paste) { "the Folder: field holds '$got'" } else { Press $c 1 }
  }
  if ($why) { [W]::PostMessage($dh, 0x0111, [IntPtr]2, [IntPtr]::Zero) | Out-Null }
  Start-Sleep 2
  if (-not $why) { $listed = Listed $want; $told = [bool](Like ($UIA::FromHandle($hw)) "That is not a folder") }
}
$shot = Shot "04d-folder-pasted"
$prompt = $hw -and (NoPrompt)
Result "a path pasted into the picker's Folder: field reaches the page" ($listed -and -not $prompt -and -not $told) $(if ($why) { $why } elseif ($prompt) { "the page asks for the path as text" } elseif ($told) { "the page says it is not a folder" } elseif ($listed) { "the welcome lists $want" } else { "the welcome does not list $want" }) $shot

# the chooser answers with the folder chosen in it: OK on what it shows first
$pick = Send "/api/pick-folder" @{ prompt = "aht check: pick any folder" }
$c = NewChooser
$shot = Shot "04b-folder-picker"
$why = if (-not $c) { "no folder chooser came up" } else { Press $c 1 }
if ($why -and $c) { [W]::PostMessage([IntPtr]$c.Current.NativeWindowHandle, 0x0111, [IntPtr]2, [IntPtr]::Zero) | Out-Null }
$said = if ($pick.Wait(15000)) { $pick.Result.Content.ReadAsStringAsync().Result | ConvertFrom-Json } else { $null }
$picked = if ($said) { $said.path } else { "" }
Result "folder picker answers with the folder" (-not $why -and $picked -and $said.chooser -eq $true) $(if ($why) { $why } else { "picked: $picked" }) $shot

# ---- 5. Continue: a console in the project folder ----
# the console starts in the folder, which is not on its command line: the
# stand-in notes where it runs
$r = Run @("resume-here", $Proj)
for ($i = 0; $i -lt 15 -and -not (Test-Path "$Box\continue-cwd.txt"); $i++) { Start-Sleep 1 }
Start-Sleep 2                  # the console draws
$con = @(Consoles)
$cwd = "$(Get-Content "$Box\continue-cwd.txt" -TotalCount 1 -ErrorAction SilentlyContinue)".Trim()
$detail = if ($r.ok) { "in: $cwd | " + ($con | Select-Object -First 1).CommandLine } else { "resume-here: code $($r.code) $($r.err)$($r.out)" }
Result "Continue opens a console in the project" ($r.ok -and $con.Count -gt 0 -and $cwd -eq $Proj) $detail (Shot "05-continue")
$con | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 1                  # its window closes with it

# ---- 6. notices, one after another, through the tray ----
# a notice still up from before (Windows keeps one on screen while nobody uses
# the machine) would cover the check's notices and take step 7's click
[W]::Wake()
$stay = ClearToasts
Result "no older notice on screen" ($stay -eq 0) $(if ($stay) { "$stay older notice(s) stayed up: the notice checks below may fail because of it" }) (Shot "05b-no-older-notice")
$q = "$env:AHT_HOME\run\tray-notices.jsonl"
$r = Run @("notices", "--test")
Start-Sleep 5
$n1 = (Test-Path $q) -and ((Get-Content $q -Raw) -like "*how a notice from aht looks*")
$s1 = Shot "06-notice"
[System.IO.File]::AppendAllText($q, '{"title": "demo-project waits for you", "message": "it needs an answer", "info": {}, "at": 0}' + "`n")
Start-Sleep 5
Result "notices reach the tray (see the two screenshots)" $n1 "the test notice is in the tray's queue" $s1
Result "a second notice in a row" $null "check the screenshot" (Shot "06b-second-notice")

# ---- 7. a click on a notice opens a window ----
$before = (Windows "aht").Count
[System.IO.File]::AppendAllText($q, '{"title": "aht check", "message": "a click here opens aht", "info": {}, "at": 0}' + "`n")
Start-Sleep 5
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
ClickAt ([int]($b.Width * 0.85)) ([int]($b.Height * 0.872))
$more = $false
for ($i = 0; $i -lt 15 -and -not $more; $i++) { Start-Sleep 1; $more = (Windows "aht").Count -gt $before }
Result "a click on a notice opens aht" $more ("aht windows: $before before" + $(if ($stay) { "; an older notice stayed up" })) (Shot "07-notice-click")

# ---- 8. Show in Explorer ----
$r = Api "/api/reveal" @{ path = $Proj }
Start-Sleep 4
$ex = WindowsLike "demo-project"         # "demo-project - File Explorer"
Result "Show in Explorer opens the folder" ($r.ok -and $ex.Count -gt 0) ($ex | ForEach-Object { $_.Current.Name }) (Shot "08-explorer")
foreach ($w in $ex) { try { ($w.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern)).Close() } catch {} }

# ---- 9. start at login, on and off ----
$on = (Run @("autostart", "on", "--json")).json
$v1 = (Get-ItemProperty $RunKey)."aht-watcher"
$off = (Run @("autostart", "off", "--json")).json
$v2 = (Get-ItemProperty $RunKey)."aht-watcher"
$alone = "`"$Dist\aht-tray.exe`" --watch"     # off: the watcher alone, no script in between
Result "start at login: on, then off" ($on.on -and $v1 -like "*aht-tray.exe*" -and -not $off.on -and $v2 -eq $alone -and -not (Test-Path "$Dist\aht-watch.vbs")) "on: $v1 / off: $v2" $null

# ---- 10. the watcher alone, as that entry starts it: running, no window ----
Ours | Where-Object { $_.CommandLine -like "* watch*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 1
$all = [System.Windows.Automation.Condition]::TrueCondition
$top = @($UIA::RootElement.FindAll($TS::Children, $all)).Count
$w = Start-Process "$Dist\aht-tray.exe" -ArgumentList "--watch" -PassThru
Start-Sleep 5
$log = (Get-Content "$env:AHT_HOME\aht-watcher.log" -Tail 3 -ErrorAction SilentlyContinue) -join " | "
$more = @($UIA::RootElement.FindAll($TS::Children, $all)).Count - $top
Result "the watcher alone runs with no window" (-not $w.HasExited -and $more -le 0 -and $log -like "*watcher*") "new windows: $more; log: $log" (Shot "10-watcher-alone")
if ($runBefore) { Set-ItemProperty $RunKey "aht-watcher" $runBefore } else { Remove-ItemProperty $RunKey "aht-watcher" -ErrorAction SilentlyContinue }

# ---- 11. Windows Security found nothing of aht's during the check ----
try {
  $hits = @(Get-MpThreatDetection -ErrorAction Stop | Where-Object { $_.InitialDetectionTime -gt $Started -and ($_.Resources -join " ") -match "aht" })
  Result "Windows Security finds nothing" ($hits.Count -eq 0) (($hits | ForEach-Object { "$($_.ThreatID): $($_.Resources -join ', ')" }) -join "; ") $null
} catch {
  Result "Windows Security finds nothing" $null "could not ask it: $($_.Exception.Message)" $null
}

# ---- the end: our processes go, the aht windows and Continue's consoles close ----
foreach ($w in (Windows "aht")) { try { ($w.GetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern)).Close() } catch {} }
Ours | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Consoles | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# ---- the machine's own watcher and tray start again, with its environment,
# not the check's (watchers first: a tray starts one when none runs) ----
if ($Theirs) {
  Start-Sleep 2
  Get-ChildItem env: | Where-Object { $_.Name -like "AHT_*" } | ForEach-Object { Remove-Item "env:$($_.Name)" }
  foreach ($k in $EnvBefore.Keys) { Set-Item "env:$k" $EnvBefore[$k] }
  $isTray = { $_.Name -eq "aht-tray.exe" -and $_.CommandLine -notlike "*--watch*" }
  foreach ($p in @($Theirs | Sort-Object $isTray)) {
    if ($p.Name -eq "aht.exe") { Start-Process $p.ExecutablePath -ArgumentList "watch" -WindowStyle Hidden }
    elseif ($p.CommandLine -like "*--watch*") { Start-Process $p.ExecutablePath -ArgumentList "--watch" }
    else { Start-Process $p.ExecutablePath }      # the tray, without opening a window
  }
  Start-Sleep 5
  $back = @(Get-CimInstance Win32_Process -Filter "name='aht.exe' or name='aht-tray.exe'" |
    Where-Object { $_.SessionId -eq $Session -and $_.ExecutablePath -and -not (InRoot $_.ExecutablePath) })
  $trays = @($Theirs | Where-Object $isTray).Count
  $again = @($back | Where-Object $isTray).Count
  Result "the machine's own tray and watcher run again" ($back.Count -gt 0 -and $again -ge [math]::Min($trays, 1)) ("stopped: " + (($Theirs | ForEach-Object { $_.CommandLine }) -join "; ")) $null
}
[W]::Rest()                    # the display may sleep again
Add-Content "$Out\results.jsonl" '{"check": "done"}'
