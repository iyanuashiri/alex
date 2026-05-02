# Load repo .env and deploy CDK stacks (Windows-friendly).
# Usage: .\deploy-with-env.ps1                    # deploy --all
#         .\deploy-with-env.ps1 Alex5Database      # deploy only listed stacks
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $StackNames = @()
)
$ErrorActionPreference = "Stop"
if (-not $env:CDK_DEFAULT_REGION) {
    $env:CDK_DEFAULT_REGION = "us-east-1"
}

$callerJson = aws sts get-caller-identity --output json 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "AWS credentials are missing or expired. Run: aws login   (or aws sso login / configure your profile), then retry."
    exit 1
}
if (-not $env:CDK_DEFAULT_ACCOUNT) {
    $caller = $callerJson | ConvertFrom-Json
    $env:CDK_DEFAULT_ACCOUNT = [string]$caller.Account
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$EnvFile = Join-Path $RepoRoot ".env"

$vectorBucket = "alex-vectors-$($env:CDK_DEFAULT_ACCOUNT)"
$ctx = @(
    "sagemakerEndpoint=alex-embedding-endpoint-cdk"
)

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) {
            return
        }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) {
            return
        }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim()
        if (
            ($val.Length -ge 2) -and (
                ($val.StartsWith('"') -and $val.EndsWith('"')) -or
                ($val.StartsWith("'") -and $val.EndsWith("'"))
            )
        ) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        switch ($key) {
            "VECTOR_BUCKET" { $vectorBucket = $val }
            "POLYGON_API_KEY" { $ctx += "polygonApiKey=$val" }
            "POLYGON_PLAN" { $ctx += "polygonPlan=$val" }
            "CLERK_JWKS_URL" { $ctx += "clerkJwksUrl=$val" }
            "CLERK_ISSUER" { $ctx += "clerkIssuer=$val" }
        }
    }
}

$ctx = @("vectorBucket=$vectorBucket") + $ctx
if ($StackNames.Count -gt 0) {
    $argList = @("cdk", "deploy") + $StackNames + @("--method", "direct", "--require-approval", "never")
}
else {
    $argList = @("cdk", "deploy", "--all", "--method", "direct", "--require-approval", "never")
}
foreach ($c in $ctx) {
    $argList += "-c"
    $argList += $c
}

Set-Location $PSScriptRoot
npm run build

# Synth first, then pre-upload file assets to the CDK bootstrap bucket. This avoids
# intermittent multi-minute stalls on template publish (Smithy client default timeout).
$synthArgs = @("cdk", "synth", "--quiet")
if ($StackNames.Count -gt 0) {
    $synthArgs += $StackNames
}
foreach ($c in $ctx) {
    $synthArgs += "-c"
    $synthArgs += $c
}
npx @synthArgs

$cdkOut = Join-Path $PSScriptRoot "cdk.out"
Get-ChildItem -Path $cdkOut -Filter "*.assets.json" -ErrorAction SilentlyContinue | ForEach-Object {
    $assets = Get-Content $_.FullName -Raw | ConvertFrom-Json
    foreach ($hash in $assets.files.PSObject.Properties.Name) {
        $entry = $assets.files.$hash
        if (-not $entry.source) {
            continue
        }
        $packaging = [string]$entry.source.packaging
        $rel = [string]$entry.source.path
        if ($rel -eq "") {
            continue
        }
        $destProps = @($entry.destinations.PSObject.Properties | ForEach-Object { $_.Value })
        if ($destProps.Count -lt 1) {
            continue
        }
        $bucket = [string]$destProps[0].bucketName
        $objectKey = [string]$destProps[0].objectKey
        if ($bucket -eq "" -or $objectKey -eq "") {
            continue
        }
        $s3Uri = "s3://$bucket/$objectKey"

        if ($packaging -eq "file") {
            $srcPath = Join-Path $cdkOut $rel
            if (-not (Test-Path -LiteralPath $srcPath)) {
                continue
            }
            aws s3 cp --region $env:CDK_DEFAULT_REGION $srcPath $s3Uri
        }
        elseif ($packaging -eq "zip") {
            $dirPath = Join-Path $cdkOut $rel
            if (-not (Test-Path -LiteralPath $dirPath -PathType Container)) {
                continue
            }
            $tmpZip = Join-Path ([System.IO.Path]::GetTempPath()) "cdk-preseed-$hash.zip"
            if (Test-Path -LiteralPath $tmpZip) {
                Remove-Item -LiteralPath $tmpZip -Force
            }
            Compress-Archive -Path (Join-Path $dirPath '*') -DestinationPath $tmpZip -CompressionLevel Fastest
            aws s3 cp --region $env:CDK_DEFAULT_REGION $tmpZip $s3Uri
            Remove-Item -LiteralPath $tmpZip -Force
        }
    }
}

# Let any prior CDK Node process release its lock on cdk.out before the deploy step.
Start-Sleep -Seconds 5
npx @argList
