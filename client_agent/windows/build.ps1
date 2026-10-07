# SPDX-License-Identifier: GPL-3.0-or-later
# Build with the .NET Framework compiler included on Windows with .NET 4.8.
param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist'))
$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (!(Test-Path $compiler)) { $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
if (!(Test-Path $compiler)) { throw '.NET Framework C# compiler not found.' }
$output = Join-Path $OutputDirectory 'Heimserver_Manager_Client_0.2.7_Windows.exe'
if (Test-Path $output) { throw 'Existing release must not be overwritten.' }
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$sources = @('I18n.cs','TrayIcons.cs','DeviceBinding.cs','ClientCore.cs','ClientForm.cs','WindowsIntegration.cs','Program.cs','ClientExtras.cs','ExtrasForm.cs') | ForEach-Object { Join-Path $PSScriptRoot $_ }
$resources = @('offline','connecting','online') | ForEach-Object { "/resource:$(Join-Path $PSScriptRoot "../icons/$_.png"),hsm.$_.png" }
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ "/out:$output" "/win32manifest:$(Join-Path $PSScriptRoot 'app.manifest')" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Runtime.Serialization.dll /r:System.Security.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll $sources $resources "/resource:$(Join-Path $PSScriptRoot 'client_en.json'),hsm.client_en.json"
if ($LASTEXITCODE -ne 0) { throw 'Compilation failed.' }
$hash = (Get-FileHash -Algorithm SHA256 $output).Hash.ToLowerInvariant()
"$hash  $([IO.Path]::GetFileName($output))" | Set-Content -Encoding ASCII (Join-Path $OutputDirectory 'SHA256SUMS')
Write-Output $output
