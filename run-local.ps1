# One-click local run on Windows:  .\run-local.ps1            (finds the kit folder itself)
#                                  .\run-local.ps1 -Kit "C:\path\to\kit"
param([string]$Kit)
$root = $PSScriptRoot
if (-not $Kit) {
  $f = Get-ChildItem "$HOME\Downloads","$HOME\Desktop","$HOME\Documents" -Recurse -Filter item_master.csv -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($f) { $Kit = if ($f.Directory.Name -eq 'master_data') { $f.Directory.Parent.FullName } else { $f.Directory.FullName } }
}
if ($Kit -and (Test-Path $Kit)) {
  Write-Host "Using kit: $Kit"
  Get-ChildItem $Kit -Recurse -Include *.csv,RC-*.pdf | Copy-Item -Destination "$root\backend\data" -Force
}
if (-not (Test-Path "$root\frontend\node_modules")) { Push-Location "$root\frontend"; npm install; Pop-Location }
Push-Location "$root\backend"
pip install -r requirements.txt
Pop-Location
$key = if ($env:GROQ_API_KEY) { "`$env:GROQ_API_KEY='$($env:GROQ_API_KEY)';" } else { "" }
$model = if ($env:GROQ_MODEL) { $env:GROQ_MODEL } else { "allam-2-7b" }
$db = if ($env:DATABASE_URL) { "`$env:DATABASE_URL='$($env:DATABASE_URL)';" } else { "`$env:DB_PATH='data/app.db';" }
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\backend'; `$env:DATA_DIR='data'; `$env:GROQ_MODEL='$model'; $key $db uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\frontend'; npm run dev"
Start-Sleep 6
Start-Process "http://localhost:3000"
