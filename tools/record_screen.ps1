# Record the operator PC's screen (the FlyHead console) to an MP4 during a field run.
#   powershell -ExecutionPolicy Bypass -File tools\record_screen.ps1                 # whole primary screen
#   powershell -ExecutionPolicy Bypass -File tools\record_screen.ps1 -Fps 10 -Out D:\rec
# Press q in this window to stop; the file is finalized then. Needs ffmpeg on PATH (winget install Gyan.FFmpeg).
# The file name carries the start time so it can be matched to runs/live_<time> and to phone videos;
# note it in the run's field_records/<run>/notes.md.
param(
    [int]$Fps = 15,
    [string]$Out = (Join-Path $PSScriptRoot '..\local\recordings')
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw 'ffmpeg not found on PATH' }
New-Item -ItemType Directory -Force $Out | Out-Null
$file = Join-Path $Out ('console_{0}.mp4' -f (Get-Date -Format 'yyyyMMdd\THHmmss'))
Write-Host "Recording to $file  (press q to stop)"
ffmpeg -hide_banner -loglevel warning -stats -f gdigrab -framerate $Fps -draw_mouse 1 -i desktop `
    -vf "scale='min(1920,iw)':-2" -c:v libx264 -threads 4 -preset veryfast -crf 26 -pix_fmt yuv420p -movflags +faststart $file
Write-Host "Saved $file"
