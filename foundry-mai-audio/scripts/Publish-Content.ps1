#requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SettingsPath,
    [Parameter(Mandatory)][ValidateSet('Upload', 'Put', 'Get', 'Head', 'List', 'Delete', 'Lockdown')][string]$Action,
    [string]$Source,
    [string]$Blob,
    [string]$OutputPath,
    [string]$Prefix = '',
    [string]$Cursor = '',
    [switch]$AllowAnonymous,
    [switch]$GenerateSamples,
    [switch]$VerifyStreaming,
    [switch]$VerifyGallery,
    [ValidateRange(60, 1800)][int]$ReadyTimeoutSeconds = 900
)
. "$PSScriptRoot\Common.ps1"

$settingsPath = [IO.Path]::GetFullPath($SettingsPath)
$lock = [IO.File]::Open("$settingsPath.lock", [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$client = $null
$token = $null
$elevated = $false
try {
    $settings = Read-PublishSettings $settingsPath
    if ($Action -eq 'Lockdown' -or $settings['publishingMayBeEnabled']) {
        Disable-Publishing $settings
        $settings.publishingMayBeEnabled = $false
        $settings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $settingsPath -Encoding utf8
        if ($Action -eq 'Lockdown') { Write-Host 'Upload API disabled; temporary Contributor revoked.'; return }
    }
    Assert-PrivateStorage $settings
    $app = Invoke-Arm $settings.appId
    Assert-PublishIdentity $settings $app
    $origin = Get-SiteOrigin $app
    $provider = @($app.properties.template.containers[0].env | Where-Object name -eq 'AUTH_PROVIDER')
    if ($provider.Count -ne 1) { throw 'No explicit reader authentication configuration found.' }
    if ($provider[0].value -eq 'none' -and -not $AllowAnonymous) {
        throw 'Readers are anonymous. Configure authentication first, or explicitly pass -AllowAnonymous for public content.'
    }
    $uploads = @()
    if ($Action -in @('Upload', 'Put')) {
        if (-not $Source) { throw '-Source is required.' }
        $sourceItem = Get-Item -LiteralPath $Source
        if ($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Symbolic links are not upload sources.' }
        if ($Action -eq 'Upload') {
            if (-not $sourceItem.PSIsContainer) { throw 'Upload requires a dedicated site directory.' }
            foreach ($file in Get-ChildItem -LiteralPath $sourceItem.FullName -File -Recurse) {
                if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Symbolic-link asset rejected: $($file.Name)" }
                $relative = [IO.Path]::GetRelativePath($sourceItem.FullName, $file.FullName).Replace('\', '/')
                if ($relative -eq 'samples.json') {
                    $manifest = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json -AsHashtable
                    if ($GenerateSamples -or @($manifest.samples).Count -eq 0) {
                        Write-Host 'Keeping the remote gallery manifest until real sample generation succeeds.'
                        continue
                    }
                }
                if ($relative -match '(^|/)\.') { throw "Hidden/dot-file asset rejected: $relative" }
                $uploads += @{ path = $file.FullName; blob = $relative; type = Get-AssetContentType $file.FullName }
            }
            if ($uploads.Count -eq 0) { throw 'No site assets found.' }
            # Upload entry points last to reduce (not eliminate) mixed-version reads.
            $uploads = @($uploads | Sort-Object { $_.blob.EndsWith('.html') }, { $_.blob })
        }
        else {
            if ($sourceItem.PSIsContainer -or -not $Blob) { throw 'Put requires one file and -Blob.' }
            $uploads = @(@{ path = $sourceItem.FullName; blob = $Blob; type = Get-AssetContentType $sourceItem.FullName })
        }
        foreach ($upload in $uploads) { $null = Get-BlobUrlPath $upload.blob }
    }
    if ($Action -in @('Get', 'Head', 'Delete')) { $null = Get-BlobUrlPath $Blob }
    if ($Action -eq 'Get' -and (-not $OutputPath -or (Test-Path -LiteralPath $OutputPath))) {
        throw 'Get requires a new -OutputPath; existing files are never overwritten.'
    }
    if (-not $settings['contributorAssignmentId']) {
        $settings.contributorAssignmentId = "$($settings.containerId)/providers/Microsoft.Authorization/roleAssignments/$([guid]::NewGuid())"
    }
    $settings.publishingMayBeEnabled = $true
    $settings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $settingsPath -Encoding utf8
    $elevated = $true
    $token = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
    $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($token))).ToLowerInvariant()
    $null = Invoke-Arm $settings.contributorAssignmentId -ApiVersion '2022-04-01' -Method put -Body @{
        properties = @{
            principalId = $settings.identityPrincipalId
            principalType = 'ServicePrincipal'
            roleDefinitionId = "/subscriptions/$($settings.subscriptionId)/providers/Microsoft.Authorization/roleDefinitions/$script:ContributorRole"
        }
    }
    $null = Set-AppVariables $settings @{ UPLOAD_API_ENABLED = 'true'; UPLOAD_API_TOKEN_SHA256 = $digest }
    $client = New-PublishClient
    $deadline = [DateTime]::UtcNow.AddSeconds($ReadyTimeoutSeconds)
    do {
        $response = Invoke-PublishRequest $client "$origin/_publish/blobs" GET -Token $token -TimeoutSeconds 60
        try {
            $status = [int]$response.StatusCode
            if ($status -eq 200) { break }
            if ($status -notin @(401, 403, 404, 429, 500, 502, 503, 504)) { throw "Unexpected readiness response: HTTP $status." }
        }
        finally { $response.Dispose() }
        if ([DateTime]::UtcNow -ge $deadline) { throw "Upload API did not become ready (HTTP $status)." }
        Start-Sleep -Seconds 5
    } while ($true)

    foreach ($upload in $uploads) {
        $uri = "$origin/_publish/blobs/$(Get-BlobUrlPath $upload.blob)"
        do {
            $stream = [IO.File]::OpenRead($upload.path)
            try { $response = Invoke-PublishRequest $client $uri PUT -Token $token -Stream $stream -ContentType $upload.type }
            finally { $stream.Dispose() }
            try {
                $status = [int]$response.StatusCode
                if ($status -in @(200, 201, 204)) { Write-Host "Uploaded $($upload.blob)"; break }
                if ($status -notin @(403, 429, 503) -or [DateTime]::UtcNow -ge $deadline) {
                    throw "Upload failed for '$($upload.blob)' (HTTP $status)."
                }
            }
            finally { $response.Dispose() }
            Start-Sleep -Seconds 5
        } while ($true)
    }
    if ($GenerateSamples) {
        $response = Invoke-PublishRequest $client "$origin/_publish/generate-samples" POST -Token $token -TimeoutSeconds 900
        try {
            if (-not $response.IsSuccessStatusCode) {
                throw "Sample generation failed (HTTP $([int]$response.StatusCode)): $($response.Content.ReadAsStringAsync().GetAwaiter().GetResult())"
            }
            Write-Host $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }
        finally { $response.Dispose() }
    }
    if ($VerifyStreaming) {
        $response = Invoke-PublishRequest $client "$origin/_publish/verify-streaming" POST -Token $token -TimeoutSeconds 180
        try {
            if (-not $response.IsSuccessStatusCode) {
                throw "Streaming verification failed (HTTP $([int]$response.StatusCode)): $($response.Content.ReadAsStringAsync().GetAwaiter().GetResult())"
            }
            Write-Host $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }
        finally { $response.Dispose() }
    }
    if ($VerifyGallery) {
        $response = Invoke-PublishRequest $client "$origin/_publish/blobs/samples.json" GET -Token $token
        try {
            if (-not $response.IsSuccessStatusCode) { throw 'Generated gallery manifest could not be read.' }
            $manifest = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json -AsHashtable
        }
        finally { $response.Dispose() }
        if (@($manifest.samples).Count -ne 8) { throw 'Expected exactly eight real gallery samples.' }
        foreach ($sample in $manifest.samples) {
            $uri = "$origin/_publish/blobs/$(Get-BlobUrlPath $sample.path)"
            $response = Invoke-PublishRequest $client $uri HEAD -Token $token
            try {
                if ([int]$response.StatusCode -ne 200 -or $response.Content.Headers.ContentType.MediaType -ne 'audio/mpeg' -or
                    $response.Content.Headers.ContentLength -le 16) { throw "Invalid audio metadata: $($sample.path)" }
            }
            finally { $response.Dispose() }
            $response = Invoke-PublishRequest $client $uri GET -Token $token
            try {
                if ([int]$response.StatusCode -ne 200) { throw "Audio retrieval failed: $($sample.path)" }
                $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
                $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
                if ($hash -ne $sample.sha256) { throw "Audio provenance hash mismatch: $($sample.path)" }
            }
            finally { $response.Dispose() }
            $response = Invoke-PublishRequest $client $uri GET -Token $token -Range 'bytes=0-15'
            try {
                if ([int]$response.StatusCode -ne 206 -or $response.Content.Headers.ContentLength -ne 16) {
                    throw "Audio range retrieval failed: $($sample.path)"
                }
            }
            finally { $response.Dispose() }
            $response = Invoke-PublishRequest $client $uri GET -Token $token -Range 'bytes=999999999-'
            try {
                if ([int]$response.StatusCode -ne 416) { throw "Invalid audio range was not rejected: $($sample.path)" }
            }
            finally { $response.Dispose() }
        }
        Write-Host 'Verified all eight gallery hashes, audio HEAD, valid 206 ranges and invalid 416 ranges through the private storage relay.'
    }
    if ($Action -in @('List', 'Get', 'Head', 'Delete')) {
        $uri = if ($Action -eq 'List') {
            Get-PublishListUrl $origin $Prefix $Cursor
        } else { "$origin/_publish/blobs/$(Get-BlobUrlPath $Blob)" }
        $method = if ($Action -eq 'List') { 'GET' } else { $Action.ToUpperInvariant() }
        do {
            $response = Invoke-PublishRequest $client $uri $method -Token $token
            if ([int]$response.StatusCode -notin @(403, 429, 503) -or [DateTime]::UtcNow -ge $deadline) { break }
            $response.Dispose()
            Start-Sleep -Seconds 5
        } while ($true)
        try {
            if (-not $response.IsSuccessStatusCode) { throw "$Action failed (HTTP $([int]$response.StatusCode))." }
            if ($Action -eq 'Get') {
                $destination = [IO.Path]::GetFullPath($OutputPath)
                $temporary = "$destination.$([guid]::NewGuid().ToString('N')).partial"
                $output = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
                $cancel = [Threading.CancellationTokenSource]::new([TimeSpan]::FromMinutes(30))
                try {
                    $response.Content.CopyToAsync($output, $cancel.Token).GetAwaiter().GetResult()
                    $output.Dispose()
                    [IO.File]::Move($temporary, $destination, $false)
                }
                finally {
                    $output.Dispose()
                    $cancel.Dispose()
                    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
                }
            }
            elseif ($Action -eq 'Head') { $response.Content.Headers.ToString() }
            elseif ($Action -eq 'List') { $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() }
        }
        finally { $response.Dispose() }
    }
}
finally {
    try {
        if ($elevated) {
            Disable-Publishing $settings
            $settings.publishingMayBeEnabled = $false
            $settings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $settingsPath -Encoding utf8
            Write-Host 'Upload API disabled; temporary Contributor revoked.'
        }
    }
    finally {
        $token = $null
        if ($client) { $client.Dispose() }
        $lock.Dispose()
    }
}
