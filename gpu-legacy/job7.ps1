cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"
"$(Get-Date -f s) MILESTONE rotating cold-cache sweep" | Add-Content $L
$env:SMOL_KBENCH=1; $env:SMOL_KB_X=1; & .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^COLD|vram free|cu err" | % Line | Add-Content $L
"$(Get-Date -f s) MILESTONE q4 classifier fallback sweep" | Add-Content $L
$env:SMOL_CLS="q4"; & .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^CLSQ4|classifier|cu err" | % Line | Add-Content $L
"$(Get-Date -f s) MILESTONE job7 done" | Add-Content $L
