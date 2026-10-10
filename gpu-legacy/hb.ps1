while(-not (Test-Path E:\temp\gpu-legacy\hb.stop)){
  $v = try { $c=(Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction Stop).CounterSamples | Measure-Object CookedValue -Sum; "{0:N0} MiB used(dedicated)" -f ($c.Sum/1MB) } catch { "vram n/a(no counter)" }
  "$(Get-Date -f s) heartbeat $v" | Add-Content E:\temp\gpu-legacy\heartbeat.log; Start-Sleep 30 }
