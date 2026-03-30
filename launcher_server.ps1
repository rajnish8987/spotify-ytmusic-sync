# Spotify -> YT Music Sync Web Launcher
# Runs a lightweight HTTP server to serve the Launcher UI and manage the Python app.

$ErrorActionPreference = "Stop"
$ScriptRoot = $PSScriptRoot

# Settings
$ServerPort = 8081
$PythonPort = 8000
$LauncherWebDir = Join-Path $ScriptRoot "launcher-web"
$BackendDir = Join-Path $ScriptRoot "backend"

# Global state to track recent logs
$Global:RecentLogs = @()

function Add-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "HH:mm:ss"
    $fullMsg = "[$timestamp] $Message"
    Write-Host $fullMsg
    $Global:RecentLogs += $Message
    if ($Global:RecentLogs.Count -gt 50) {
        $Global:RecentLogs = $Global:RecentLogs[-50..-1]
    }
}

# --- Process Management ---
function Get-PythonProcess {
    $connections = netstat -aon | Select-String "LISTENING" | Select-String ":$PythonPort\s"
    foreach ($line in $connections) {
        $parts = ($line -replace '\s+', ' ').Trim().Split(' ')
        $targetPid = $parts[-1]
        if ($targetPid -and $targetPid -ne '0' -and $targetPid -match '^\d+$') {
            return $targetPid
        }
    }
    return $null
}

function Start-PythonApp {
    $pidStr = Get-PythonProcess
    if ($pidStr) {
        Add-Log "App is already running on port $PythonPort (PID $pidStr)."
        return $true
    }

    if (Test-Path (Join-Path $BackendDir "requirements.txt")) {
        Add-Log "Installing python dependencies..."
        # Run pip install synchronously
        $pipProc = Start-Process -FilePath "pip" -ArgumentList "install -r requirements.txt --quiet" -WorkingDirectory $BackendDir -NoNewWindow -PassThru -Wait
        if ($pipProc.ExitCode -ne 0) {
            Add-Log "ERROR: pip install failed. Make sure Python/Pip is on PATH."
            return $false
        }
    } else {
        Add-Log "WARNING: requirements.txt not found. Skipping dependency install."
    }

    
    Add-Log "Starting FastAPI server on port $PythonPort..."
    
    # Run uvicorn completely hidden
    Start-Process -FilePath "python" -ArgumentList "-m uvicorn main:app --host 127.0.0.1 --port $PythonPort" -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru | Out-Null
    
    Start-Sleep -Seconds 2
    $newPid = Get-PythonProcess
    if ($newPid) {
        Add-Log "Server started successfully (PID $newPid)."
        return $true
    } else {
        Add-Log "ERROR: Server failed to start."
        return $false
    }
}

function Stop-PythonApp {
    $pidStr = Get-PythonProcess
    if (-not $pidStr) {
        Add-Log "No server running on port $PythonPort."
        return $true
    }

    try {
        Stop-Process -Id ([int]$pidStr) -Force -ErrorAction Stop
        Add-Log "Stopped Python server (PID $pidStr)."
        return $true
    } catch {
        Add-Log "ERROR: Could not kill PID $pidStr ($_)"
        return $false
    }
}

# --- HTTP Server ---
function Send-Response {
    param(
        [System.Net.HttpListenerResponse]$Response,
        [int]$StatusCode = 200,
        [string]$ContentType = "application/json",
        [string]$Content = ""
    )
    try {
        $Response.StatusCode = $StatusCode
        $Response.ContentType = $ContentType
        # Add CORS support
        $Response.Headers.Add("Access-Control-Allow-Origin", "*")
        $Response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        
        if ($Content) {
            $buffer = [System.Text.Encoding]::UTF8.GetBytes($Content)
            $Response.ContentLength64 = $buffer.Length
            $Response.OutputStream.Write($buffer, 0, $buffer.Length)
        }
        $Response.Close()
    } catch {
        # Client may have disconnected
    }
}

function Start-ApiServer {
    $listener = New-Object System.Net.HttpListener
    $listener.Prefixes.Add("http://localhost:$ServerPort/")
    $listener.Prefixes.Add("http://127.0.0.1:$ServerPort/")
    
    try {
        $listener.Start()
        Add-Log "Web Launcher API running on http://localhost:$ServerPort"
    } catch {
        Write-Host "ERROR: Could not start listener on port $ServerPort. Is it already running?" -ForegroundColor Red
        return
    }

    # Open the UI in browser
    Start-Process "http://localhost:$ServerPort/"

    try {
        while ($listener.IsListening) {
            $context = $listener.GetContext()
            $request = $context.Request
            $response = $context.Response
            
            $path = $request.Url.LocalPath.TrimEnd('/')
            if ($path -eq "") { $path = "/index.html" }
            
            # --- Handle Static Files ---
            if ($path -notmatch "^/api/") {
                $filePath = Join-Path $LauncherWebDir ($path -replace '/', '\')
                if (Test-Path $filePath -PathType Leaf) {
                    $ext = [System.IO.Path]::GetExtension($filePath).ToLower()
                    $contentType = switch ($ext) {
                        ".html" { "text/html" }
                        ".css"  { "text/css" }
                        ".js"   { "application/javascript" }
                        ".json" { "application/json" }
                        ".png"  { "image/png" }
                        ".ico"  { "image/x-icon" }
                        default { "application/octet-stream" }
                    }
                    try {
                        $buffer = [System.IO.File]::ReadAllBytes($filePath)
                        $response.StatusCode = 200
                        $response.ContentType = $contentType
                        $response.ContentLength64 = $buffer.Length
                        $response.OutputStream.Write($buffer, 0, $buffer.Length)
                        $response.Close()
                    } catch {
                        Send-Response -Response $response -StatusCode 500 -Content "Error reading file"
                    }
                } else {
                    Send-Response -Response $response -StatusCode 404 -Content "404 Not Found"
                }
                continue
            }
            
            # --- Handle CORS Preflight ---
            if ($request.HttpMethod -eq "OPTIONS") {
                Send-Response -Response $response -StatusCode 204
                continue
            }
            
            # --- Handle API endpoints ---
            try {
                switch ($request.HttpMethod) {
                    "GET" {
                        if ($path -eq "/api/status") {
                            $isRunning = (Get-PythonProcess) -ne $null
                            
                            # Grab logs and clear them so we don't send duplicates
                            $logsToSend = $Global:RecentLogs
                            $Global:RecentLogs = @()
                            
                            $json = @{
                                running = $isRunning
                                logs = $logsToSend
                            } | ConvertTo-Json -Compress
                            
                            Send-Response -Response $response -StatusCode 200 -Content $json
                        } else {
                            Send-Response -Response $response -StatusCode 404 -Content "{`"error`":`"Not found`"}"
                        }
                    }
                    
                    "POST" {
                        if ($path -eq "/api/start") {
                            # Write a tiny launcher script to robustly start the backend detached
                            $tempLauncher = Join-Path $BackendDir "_start_backend.ps1"
                            $launcherCode = @"
Set-Location -Path `"$BackendDir`"
if (Test-Path `"`$BackendDir\requirements.txt`") {
    Start-Process -FilePath `"pip`" -ArgumentList `"install -r requirements.txt --quiet`" -Wait -WindowStyle Hidden -RedirectStandardOutput `"pip_log.txt`" -RedirectStandardError `"pip_err.txt`"
}

Start-Process -FilePath `"python`" -ArgumentList `"-m uvicorn main:app --host 127.0.0.1 --port $PythonPort`" -WindowStyle Hidden -RedirectStandardOutput `"app_log.txt`" -RedirectStandardError `"app_err.txt`"
"@
                            Set-Content -Path $tempLauncher -Value $launcherCode
                            
                            # Run it completely hidden and detached
                            Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$tempLauncher`"" -WindowStyle Hidden -PassThru | Out-Null
                            
                            Send-Response -Response $response -StatusCode 200 -Content "{`"status`":`"starting`"}"
                        }
                        elseif ($path -eq "/api/stop") {
                            $success = Stop-PythonApp
                            if ($success) {
                                Send-Response -Response $response -StatusCode 200 -Content "{`"status`":`"stopped`"}"
                            } else {
                                Send-Response -Response $response -StatusCode 500 -Content "{`"error`":`"failed to stop`"}"
                            }
                        }
                        else {
                            Send-Response -Response $response -StatusCode 404 -Content "{`"error`":`"Not found`"}"
                        }
                    }
                    
                    default {
                        Send-Response -Response $response -StatusCode 405 -Content "{`"error`":`"Method not allowed`"}"
                    }
                }
            } catch {
                Add-Log "API Error: $_"
                Send-Response -Response $response -StatusCode 500 -Content "{`"error`":`"Internal Server Error`"}"
            }
        }
    } finally {
        $listener.Stop()
        $listener.Close()
        Add-Log "Listener stopped."
    }
}

# Ensure launcher UI directory exists
if (-not (Test-Path $LauncherWebDir)) {
    Write-Host "ERROR: launcher-web directory not found." -ForegroundColor Red
    Start-Sleep -Seconds 5
    exit
}

Add-Log "Starting Spotify Sync Web Launcher Server..."
Start-ApiServer
