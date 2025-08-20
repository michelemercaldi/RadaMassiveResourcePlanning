param (
    [Parameter(Mandatory=$false, Position=0)]
    [string]$Action = "noop"
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptName = Split-Path -Leaf $MyInvocation.MyCommand.Path

Write-Host "You entered: '$Action'"
#Write-Host "script dir: '$scriptDir'"
#Write-Host "script name: '$scriptName'"


function Run-Web-Server {
    cd $scriptDir
    poetry run uvicorn pmas_web.server:app --host 0.0.0.0 --port 8000 --reload
}


function Continuous-CLI {
    $curl= "curl"
    $curlcmd = ".\.venv\Scripts\python.exe .\pianificazione\pianificazione_massiva.py"
    #$cmd2 = ".\.venv\Scripts\python.exe .\pianificazione\pianificazione_massiva_visualizer_YW.py"
    $response_in_json = $false

    $LTIME = 0  # Initialize last modification time
    cd $scriptDir
    while ($true) {
        # Get the latest modification time of files in the directory, excluding obj, bin, .vs directories and .swp files
        $ATIME = Get-ChildItem -Path $ADIR -Recurse -File `
            | Where-Object { $_.FullName -notmatch '\\(obj|bin|logs|\.vs|\.venv|\.vscode|__pycache__)\\' -and $_.Extension -ne '.swp' } `
            | Sort-Object LastWriteTime `
            | Select-Object -Last 1 `
            | ForEach-Object { $_.LastWriteTime.ToFileTime() }
        # If the latest modification time has changed, run command
        if ($ATIME -ne $LTIME) {
            Write-Host ""
            Start-Sleep 2
            Write-Host "-------------------------------------------------"
            Write-Host "$curlcmd"
            Write-Host ""
            if ($response_in_json) {
                Invoke-Expression $curlcmd  | ConvertFrom-Json | ConvertTo-Json 
            } else {
                Invoke-Expression $curlcmd
                #Invoke-Expression $cmd2
            }
            Write-Host ""
            $LTIME = $ATIME
        }
        # Output a dot for every iteration to show it's running
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 3
    }
}


# Define commands for each action
$commands = @{
    "web"  = { Run-Web-Server }
    "cli"   = { Continuous-CLI }
}

# Help message (displayed on error or invalid input)
function Show-Help {
    Write-Host @"

USAGE: $scriptName <Action>

VALID ACTIONS:
  web   : Start the web server
  cli   : Run in continuous CLI test mode
"@ -ForegroundColor Yellow
    exit 1
}


# Execute the selected command
try {
    Write-Host "Running [$Action]..." -ForegroundColor Cyan
    & $commands[$Action]
} catch {
    Write-Error "Invalid action or command failed: $_"
    Show-Help
}
