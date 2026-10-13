$ErrorActionPreference = "Continue"
$sw = [Diagnostics.Stopwatch]::StartNew()
try {
  $w = Invoke-RestMethod "http://127.0.0.1:5000/api/v1/locations/water?lat=13.08&lon=80.27" -TimeoutSec 60
  $sw.Stop()
  $n = $w.data.water.nearby
  $d = if ($w.data.water.nearest) { $w.data.water.nearest.distance_m } else { "-" }
  Write-Output "chennai elapsed=$([math]::Round($sw.Elapsed.TotalSeconds,2))s primary='$($w.data.water.primary)' nearby=$($n.Count) exact=$($w.data.water.exact) nearest=${d}m"
  if ($n.Count -gt 0) { Write-Output ("  first: {0} / {1} / {2}m" -f $n[0].name, $n[0].type, $n[0].distance_m) }
} catch {
  $sw.Stop()
  Write-Output "chennai FAILED after $([math]::Round($sw.Elapsed.TotalSeconds,2))s : $($_.Exception.Message)"
}
$sw.Restart()
try {
  $w2 = Invoke-RestMethod "http://127.0.0.1:5000/api/v1/locations/water?lat=25.32&lon=83.01" -TimeoutSec 60
  $sw.Stop()
  $d2 = if ($w2.data.water.nearest) { $w2.data.water.nearest.distance_m } else { "-" }
  Write-Output "varanasi elapsed=$([math]::Round($sw.Elapsed.TotalSeconds,2))s nearby=$($w2.data.water.nearby.Count) nearest=${d2}m"
} catch {
  $sw.Stop()
  Write-Output "varanasi FAILED after $([math]::Round($sw.Elapsed.TotalSeconds,2))s : $($_.Exception.Message)"
}