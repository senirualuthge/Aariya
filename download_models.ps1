$baseUrl = "https://raw.githubusercontent.com/justadudewhohacks/face-api.js/master/weights"
$files = @(
    "tiny_face_detector_model-weights_manifest.json",
    "tiny_face_detector_model-shard1",
    "face_landmark_68_model-weights_manifest.json",
    "face_landmark_68_model-shard1",
    "face_expression_model-weights_manifest.json",
    "face_expression_model-shard1"
)

$destDir = "public/models"
if (!(Test-Path -Path $destDir)) {
    New-Item -ItemType Directory -Path $destDir -Force
}

foreach ($file in $files) {
    $url = "$baseUrl/$file"
    $output = "$destDir/$file"
    Write-Host "Downloading $file..."
    Invoke-WebRequest -Uri $url -OutFile $output
}
Write-Host "Download complete."
