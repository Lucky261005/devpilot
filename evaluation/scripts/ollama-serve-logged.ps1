# Start Ollama in this window with debug logging, listening on localhost only.
# Defaults match the machine used for the 2026-10-17 runs; override with -ModelsDir / -LogFile.
param(
    [string]$ModelsDir = $(if ($env:OLLAMA_MODELS) { $env:OLLAMA_MODELS } else { 'D:\ollama\models' }),
    [string]$LogFile = 'D:\ollama\server.log'
)
$env:OLLAMA_MODELS = $ModelsDir
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_DEBUG = '1'
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve 2>&1 | Tee-Object -FilePath $LogFile
