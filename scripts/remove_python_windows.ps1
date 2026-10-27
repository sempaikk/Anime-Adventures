#requires -Version 5.1
[CmdletBinding()]
param([switch]$Preview, [switch]$RemoveBotFiles)

# Uses registered official uninstallers, never deletes Windows/Installer or
# embedded runtimes inside unrelated applications. No Python is required.
$ErrorActionPreference = 'Stop'
$BotDirectory = 'D:\Armazenamento do Bot'
$Failures = New-Object 'System.Collections.Generic.List[string]'
$InstalledRoots = New-Object 'System.Collections.Generic.List[string]'

function Get-PythonPrograms {
    $keys = @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
              'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
              'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')
    foreach ($key in $keys) {
        if (-not (Test-Path -LiteralPath $key)) { continue }
        foreach ($child in @(Get-ChildItem -LiteralPath $key -ErrorAction SilentlyContinue)) {
            $entry = Get-ItemProperty -LiteralPath $child.PSPath -ErrorAction SilentlyContinue
            if (-not $entry) { continue }
            if ($entry.SystemComponent -eq 1 -and $entry.DisplayName -ne 'Python Launcher') { continue }
            $python = $entry.Publisher -match 'Python\s*Software\s*Foundation' -and $entry.DisplayName -match '^Python(?:\s+\d|\s+Launcher|\s+Install Manager)'
            $distribution = $entry.DisplayName -match '^(?:Anaconda\d?|Miniconda\d?|WinPython|PyPy|IronPython)(?:\s|\d|$)'
            if ($python -or $distribution) { $entry }
        }
    }
}

function Remove-KnownTree([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $protected = @([IO.Path]::GetPathRoot($full).TrimEnd('\'), $env:USERPROFILE, $env:WINDIR,
                   $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData)
    if ($protected -contains $full) { throw 'Refusing to remove a protected root.' }
    if ($Preview) { Write-Host "Would remove: $full"; return }
    $item = Get-Item -LiteralPath $full -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        # Remove only the link, never descend into its target.
        if ($item.PSIsContainer) { [IO.Directory]::Delete($full) }
        else { Remove-Item -LiteralPath $full -Force }
        return
    }
    if ($item.PSIsContainer) {
        foreach ($child in @(Get-ChildItem -LiteralPath $full -Force)) { Remove-KnownTree $child.FullName }
        Remove-Item -LiteralPath $full -Force
    } else { Remove-Item -LiteralPath $full -Force }
}

function Invoke-RegisteredUninstall($Entry) {
    Write-Host "Uninstalling: $($Entry.DisplayName)"
    if ($Entry.InstallLocation) {
        $location = [string]$Entry.InstallLocation
        # Only conventional dedicated interpreter folders become cleanup roots.
        if ((Split-Path $location.TrimEnd('\') -Leaf) -match '^(?:Python\d+(?:-\d+)?|Anaconda\d?|Miniconda\d?)$') {
            $InstalledRoots.Add($location)
        }
    }
    if ($Preview) { return }
    try {
        if ($Entry.WindowsInstaller -eq 1 -and $Entry.PSChildName -match '^\{[0-9A-Fa-f-]{36}\}$') {
            $exe = Join-Path $env:WINDIR 'System32\msiexec.exe'
            $arguments = '/x ' + $Entry.PSChildName + ' /passive /norestart'
        } else {
            $command = [string]$Entry.QuietUninstallString
            $quiet = [bool]$command
            if (-not $command) { $command = [string]$Entry.UninstallString }
            if ($command -notmatch '^(?:"([^"]+)"|(\S+))(?:\s+(.*))?$') { throw 'No usable registered uninstaller.' }
            $exe = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
            $arguments = [string]$Matches[3]
            # Invoke an executable directly, never evaluate registry text as shell code.
            if ([IO.Path]::GetExtension($exe) -ne '.exe' -or (Split-Path $exe -Leaf) -match '^(?:cmd|powershell|pwsh|wscript|cscript)\.exe$') {
                throw 'Unsupported registered uninstaller; use Installed apps for this entry.'
            }
            if (-not $quiet -and $Entry.Publisher -match 'Python\s*Software\s*Foundation' -and (Split-Path $exe -Leaf) -match '^python-') {
                if ($arguments -notmatch '(?i)/uninstall') { $arguments += ' /uninstall' }
                $arguments += ' /passive /norestart'
            }
        }
        $launch = @{FilePath=$exe; Wait=$true; PassThru=$true}
        if ($arguments) { $launch.ArgumentList=$arguments }
        $process = Start-Process @launch
        if ($process.ExitCode -notin @(0, 1605, 1614, 3010)) { throw "Uninstaller exit code: $($process.ExitCode)" }
        if ($process.ExitCode -eq 3010) { Write-Host 'Windows requests a restart after cleanup.' }
    } catch {
        $Failures.Add([string]$Entry.DisplayName)
        Write-Warning "Could not remove $($Entry.DisplayName). Use Windows Settings > Apps if it remains."
    }
}

function Remove-ProjectStartupShortcuts {
    $startup = [Environment]::GetFolderPath('Startup')
    if (-not (Test-Path -LiteralPath $startup)) { return }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($link in @(Get-ChildItem -LiteralPath $startup -Filter '*.lnk' -File)) {
        $shortcut = $shell.CreateShortcut($link.FullName)
        if ($shortcut.TargetPath -and $shortcut.TargetPath.StartsWith($BotDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) {
            if ($Preview) { Write-Host "Would remove startup shortcut: $($link.Name)" }
            else { Remove-Item -LiteralPath $link.FullName -Force }
        }
    }
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'This script is for Windows only.' }
Write-Host 'Remove registered Python installations and known Python residues.'
if ($RemoveBotFiles) { Write-Host "Project files will also be erased: $BotDirectory" }
Write-Host 'This does not change the bot hosting instance.'

# Stop only this companion, not Python processes belonging to other software.
$companion = [regex]::Escape((Join-Path $BotDirectory 'knowledge_pc.py'))
foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue)) {
    if ($process.CommandLine -match $companion) {
        if ($Preview) { Write-Host "Would stop companion PID $($process.ProcessId)" }
        else { Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue }
    }
}
Remove-ProjectStartupShortcuts

$programs = @(Get-PythonPrograms | Sort-Object @{Expression={ if ($_.DisplayName -match 'Launcher|Install Manager') { 1 } else { 0 } }}, PSPath -Unique)
if (-not $programs.Count) { Write-Host 'No registered desktop Python installation found.' }
foreach ($entry in $programs) { Invoke-RegisteredUninstall $entry }

$storeChecked = $false
try {
    $packages = @(Get-AppxPackage -ErrorAction Stop | Where-Object { $_.Name -like 'PythonSoftwareFoundation.Python.*' -or $_.Name -like 'PythonSoftwareFoundation.PythonManager*' })
    foreach ($package in $packages) {
        Write-Host "Removing Microsoft Store package: $($package.Name)"
        if (-not $Preview) {
            try { Remove-AppxPackage -Package $package.PackageFullName -ErrorAction Stop }
            catch { $Failures.Add($package.Name); Write-Warning 'A Store Python package could not be removed.' }
        }
    }
    $storeChecked = $true
} catch { Write-Warning 'Store packages could not be checked. Check Installed apps manually.' }

$remaining = @(Get-PythonPrograms)
if (-not $remaining.Count -and -not $Failures.Count -and $storeChecked) {
    $roots = @((Join-Path $env:LOCALAPPDATA 'Programs\Python'), (Join-Path $env:LOCALAPPDATA 'Python'),
               (Join-Path $env:APPDATA 'Python'), (Join-Path $env:LOCALAPPDATA 'pip'), (Join-Path $env:APPDATA 'pip')) + @($InstalledRoots)
    foreach ($root in @($roots | Select-Object -Unique)) {
        try { Remove-KnownTree $root }
        catch { Write-Warning "Could not finish cleaning: $root" }
    }
    try { Remove-KnownTree (Join-Path $env:USERPROFILE '.python_history') } catch { }
    foreach ($scope in @('User','Machine')) {
        try {
            $pathValue = [Environment]::GetEnvironmentVariable('Path', $scope)
            $kept = foreach ($part in ($pathValue -split ';')) {
                if (-not $part) { continue }
                $expanded = [Environment]::ExpandEnvironmentVariables($part.Trim('"').TrimEnd('\'))
                $pythonPath = $false
                foreach ($root in $roots) {
                    $prefix = $root.TrimEnd('\')
                    if ($expanded.Equals($prefix,[StringComparison]::OrdinalIgnoreCase) -or $expanded.StartsWith($prefix+'\',[StringComparison]::OrdinalIgnoreCase)) { $pythonPath=$true; break }
                }
                if (-not $pythonPath) { $part }
            }
            if (-not $Preview) {
                [Environment]::SetEnvironmentVariable('Path',($kept -join ';'),$scope)
                foreach ($name in @('PYTHONHOME','PYTHONPATH','PY_PYTHON','PY_PYTHON3')) { [Environment]::SetEnvironmentVariable($name,$null,$scope) }
            }
        } catch { Write-Warning "Could not finish environment cleanup for $scope; administrator permission may be required." }
    }
    if (-not $Preview -and (Test-Path 'HKCU:\Software\Python')) { Remove-Item -LiteralPath 'HKCU:\Software\Python' -Recurse -Force }
} else { Write-Warning 'Some installations remain or were not checked; their shared folders were preserved.' }

if ($RemoveBotFiles) {
    try { Remove-KnownTree $BotDirectory }
    catch { Write-Warning 'Close windows using the bot folder and remove it manually.' }
}
Write-Host ''
Write-Host 'Finished. Review any warnings above. Restart Windows if an uninstaller requested it.'
Write-Host 'Portable interpreters outside known folders and embedded runtimes in other apps are not erased.'
Write-Host 'If python opens Microsoft Store afterward, disable its App execution aliases in Windows Settings.'
if (-not $Preview -and ($remaining.Count -or $Failures.Count -or -not $storeChecked)) { exit 1 }
