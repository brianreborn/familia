cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"
"$(Get-Date -f s) MILESTONE replay-sequence tuning (q8 cls)" | Add-Content $L
$env:SMOL_KBENCH=1; $env:SMOL_KB_REPLAY=1; & .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^REPLAY|vram free|cu err" | % Line | Add-Content $L
"$(Get-Date -f s) MILESTONE replay-sequence tuning (q4 cls)" | Add-Content $L
$env:SMOL_CLS="q4"; & .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^REPLAY|cu err" | % Line | Add-Content $L
"$(Get-Date -f s) MILESTONE job9 done" | Add-Content $L
