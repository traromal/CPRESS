# Adds simple Explorer context menu entries for cpress (compress/extract)
# Run in elevated PowerShell

$python = (Get-Command python).Source
$cpress = "cpress"

# Compress selected items
New-Item -Path "HKCR:\*\shell\cpress_compress" -Force | Out-Null
Set-ItemProperty "HKCR:\*\shell\cpress_compress" -Name "MUIVerb" -Value "Compress with cpress"
Set-ItemProperty "HKCR:\*\shell\cpress_compress" -Name "Icon" -Value "%SystemRoot%\\System32\\shell32.dll,258"
New-Item -Path "HKCR:\*\shell\cpress_compress\command" -Force | Out-Null
Set-ItemProperty "HKCR:\*\shell\cpress_compress\command" -Name "" -Value "\"$python\" -m $cpress compress \"%1\" -o \"%1.zip\" --overwrite"

# Extract archive
New-Item -Path "HKCR:\*\shell\cpress_extract" -Force | Out-Null
Set-ItemProperty "HKCR:\*\shell\cpress_extract" -Name "MUIVerb" -Value "Extract with cpress"
Set-ItemProperty "HKCR:\*\shell\cpress_extract" -Name "Icon" -Value "%SystemRoot%\\System32\\shell32.dll,259"
New-Item -Path "HKCR:\*\shell\cpress_extract\command" -Force | Out-Null
Set-ItemProperty "HKCR:\*\shell\cpress_extract\command" -Name "" -Value "\"$python\" -m $cpress extract \"%1\" -d \"%1_extracted\""

Write-Host "Context menu entries installed (may require Explorer restart)."
