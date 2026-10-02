param([string]$Destination = '.azure-deploy/switzerlandnorth-dev')
$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$source = Join-Path $repoRoot 'infra/azure'
$target = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Destination))
if (-not $target.StartsWith($repoRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The deployment directory must stay inside this repository.'
}
if (Test-Path -LiteralPath $target) {
    throw "Destination already exists: $target. Reuse it deliberately or choose a NEW destination; no existing state or configuration is overwritten."
}
New-Item -ItemType Directory -Path $target | Out-Null
Get-ChildItem -LiteralPath $source -Filter '*.tf' -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $target
}
foreach ($name in @('.terraform.lock.hcl', 'terraform.tfvars.example', 'backend.hcl.example')) {
    Copy-Item -LiteralPath (Join-Path $source $name) -Destination $target
}
Copy-Item -LiteralPath (Join-Path $source 'tests') -Destination $target -Recurse
Copy-Item -LiteralPath (Join-Path $target 'terraform.tfvars.example') -Destination (Join-Path $target 'terraform.tfvars')
Copy-Item -LiteralPath (Join-Path $target 'backend.hcl.example') -Destination (Join-Path $target 'backend.hcl')
Write-Output "Prepared a CLEAN Terraform working directory: $target"
Write-Output 'Edit terraform.tfvars and backend.hcl, set TF_VAR_entsoe_api_token, then initialize the NEW remote state.'
Write-Output 'Source .terraform directories, existing tfvars, local states and credentials were not copied.'
