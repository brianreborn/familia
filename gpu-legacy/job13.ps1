cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"; $B="E:\temp\llama-cpu\llama-bench.exe"
gcc -O2 -march=native -o out\smol_sm11.exe smol_sm11.c -lm *>> $L; if($LASTEXITCODE){ "BUILD FAILED" | Add-Content $L; exit }
"$(Get-Date -f s) MILESTONE job13 replay: attn/rope share + q8 classifier tiles" | Add-Content $L
$env:SMOL_KBENCH=1; $env:SMOL_KB_REPLAY=1; & .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^REPLAY|cu err" | % Line | Add-Content $L
Remove-Item Env:SMOL_KBENCH,Env:SMOL_KB_REPLAY
"$(Get-Date -f s) MILESTONE job13 CPU coder matrix (SmolLM2-135M Q4_0 on CPU as coder proxy), alone then with GPU node" | Add-Content $L
$cfgs=@("-t 1 -C 0x1 --cpu-strict 1","-t 1","-t 2","-t 2 -C 0x3 --cpu-strict 1","-t 1 -C 0x1 --cpu-strict 1 --poll 0","-t 1 -C 0x1 --cpu-strict 1 -ctk q8_0 -ctv q8_0 -fa 1","-t 1 -C 0x1 --cpu-strict 1 -ub 64")
function CB($a){ $o=(& $B -m $M -p 64 -n 32 -r 1 $a.Split(' ') 2>$null | Out-String); $pp=([regex]::Match($o,'pp64\s*\|\s*([0-9.]+)')).Groups[1].Value; $tg=([regex]::Match($o,'tg32\s*\|\s*([0-9.]+)')).Groups[1].Value; "pp64=$pp tg32=$tg" }
& $B -m $M -p 0 -n 16 -r 1 -t 1 2>$null | Out-Null
foreach($c in $cfgs){ "CPUA [$c] $(CB $c)" | Add-Content $L }
Remove-Item gpu.stop -ErrorAction SilentlyContinue
$g=Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList "-NoProfile -Command `"cd E:\temp\gpu-legacy; while(-not (Test-Path gpu.stop)){ `$p=Start-Process .\out\smol_sm11.exe -ArgumentList '$M 1,2,3;8530,128;65,42,14;1,2,3 32 serve 2' -PassThru -NoNewWindow -RedirectStandardOutput gpu_bg.txt; try{`$p.ProcessorAffinity=2}catch{}; `$p.WaitForExit(); (Get-Content gpu_bg.txt | Select-String '^serve').Line | Add-Content gpu_bg.log }`""
Start-Sleep 8
foreach($c in $cfgs){ "CPUC [$c] $(CB $c)" | Add-Content $L }
New-Item gpu.stop -Force | Out-Null; $g.WaitForExit(60000) | Out-Null
"GPUBG during CPU matrix: " + ((Get-Content gpu_bg.log -ErrorAction SilentlyContinue | % { ([regex]::Match($_,'([0-9.]+) tok/s')).Groups[1].Value }) -join ',') | Add-Content $L
"$(Get-Date -f s) MILESTONE job13 done" | Add-Content $L
