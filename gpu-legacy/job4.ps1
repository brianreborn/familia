cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"
"$(Get-Date -f s) MILESTONE kbench v5 sweep + q8 classifier tex sweep" | Add-Content $L
$env:SMOL_KBENCH=1; $env:SMOL_KB_ONLYNEW=1
foreach($v in 1,0){ $env:SMOL_V5=$v; if($v -eq 0){$env:SMOL_KB_SKIPQ4=1}; & .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^q[48]m[v ]|vram free|cu err" | % Line | Add-Content $L }
"$(Get-Date -f s) MILESTONE job4 done" | Add-Content $L
