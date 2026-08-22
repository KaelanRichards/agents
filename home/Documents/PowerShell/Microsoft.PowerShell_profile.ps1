# ============================================
# PowerShell 7 Profile for Claude Code Development
# ============================================

# Add Claude Code to PATH
$env:PATH += ";$env:USERPROFILE\.local\bin"

# ============================================
# mise - activate the portable managed toolchain
# ============================================
if (Get-Command mise -ErrorAction SilentlyContinue) {
    (&mise activate pwsh) | Out-String | Invoke-Expression
}

# Oh My Posh - Beautiful prompt
if (Get-Command oh-my-posh -ErrorAction SilentlyContinue) {
    oh-my-posh init pwsh --config "$env:USERPROFILE\.config\oh-my-posh\themes\agnoster.omp.json" | Invoke-Expression
}

# Terminal Icons - File/folder icons in listings
if (Get-Module -ListAvailable -Name Terminal-Icons) {
    Import-Module Terminal-Icons
}

# PSReadLine - Intelligent autocomplete (only in interactive mode)
if ($Host.Name -eq 'ConsoleHost' -and [Console]::IsOutputRedirected -eq $false) {
    Import-Module PSReadLine
    Set-PSReadLineOption -PredictionSource History -ErrorAction SilentlyContinue
    Set-PSReadLineOption -PredictionViewStyle InlineView -ErrorAction SilentlyContinue
    Set-PSReadLineOption -EditMode Windows
    Set-PSReadLineKeyHandler -Key Tab -Function MenuComplete
    Set-PSReadLineKeyHandler -Key UpArrow -Function HistorySearchBackward
    Set-PSReadLineKeyHandler -Key DownArrow -Function HistorySearchForward
}

# ============================================
# Aliases (Mac/Linux-like commands)
# ============================================
Set-Alias -Name ll -Value Get-ChildItem -Option AllScope -Force
Set-Alias -Name which -Value Get-Command -Option AllScope -Force
Set-Alias -Name grep -Value Select-String -Option AllScope -Force

function touch { param($file) New-Item -ItemType File -Path $file -Force }
function mkcd { param($dir) New-Item -ItemType Directory -Path $dir -Force; Set-Location $dir }
function .. { Set-Location .. }
function ... { Set-Location ../.. }
function .... { Set-Location ../../.. }

# Open current directory in Explorer
function open { explorer . }

# Quick edit profile
function Edit-Profile { code $PROFILE }

# ============================================
# Claude Code Helpers
# ============================================
function cc { claude $args }
function ccv { claude --verbose $args }

# ============================================
# Git Shortcuts
# ============================================
function gs { git status }
function ga { git add $args }
function gaa { git add . }
function gcm { param($msg) git commit -m $msg }
function gp { git push }
function gpl { git pull }
function gl { git log --oneline -10 }
function gd { git diff }
function gb { git branch }
function gco { git checkout $args }

# ============================================
# Development Helpers
# ============================================
function nr { npm run $args }
function ni { npm install $args }
function py { python $args }

# Quick navigation
function projects { Set-Location ~/Projects }
function desktop { Set-Location ~/Desktop }
function downloads { Set-Location ~/Downloads }

# ============================================
# Startup Message
# ============================================
Write-Host "PowerShell $($PSVersionTable.PSVersion) | Claude Code Ready" -ForegroundColor Cyan
Write-Host "Type 'cc' to start Claude Code" -ForegroundColor DarkGray
