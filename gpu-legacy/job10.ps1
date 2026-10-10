cd E:\temp\gpu-legacy; $env:PATH="E:\temp\tools\mingw64\bin;$env:PATH"; $L="E:\temp\gpu-legacy\progress.log"; $M="E:\temp\models\SmolLM2-135M-Instruct.Q4_0.gguf"
gcc -O2 -march=native -o out\smol_sm11.exe smol_sm11.c -lm *>> $L; if($LASTEXITCODE){ "BUILD FAILED" | Add-Content $L; exit }
"$(Get-Date -f s) MILESTONE replay tuning (q8 cls)" | Add-Content $L
$env:SMOL_KBENCH=1; $env:SMOL_KB_REPLAY=1; $r8=& .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^REPLAY|cu err" | % Line; $r8 | Add-Content $L
$env:SMOL_CLS="q4"; $r4=& .\out\smol_sm11.exe $M "1,2,3" 2 gpu 2>&1 | Select-String "^REPLAY|cu err" | % Line; $r4 | % { "q4cls $_" } | Add-Content $L
Remove-Item Env:SMOL_KBENCH,Env:SMOL_KB_REPLAY,Env:SMOL_CLS
function Cfg($lines){ $h=@{}; foreach($x in $lines){ if($x -match 'pass 1 shape (\d) best MR=(\d+) RG=(\d+) BG=(\d+) G=(\d+)'){ $h["SMOL_XS$($matches[1])"]="$($matches[2]),$($matches[3]),$($matches[4]),$($matches[5])" } }; $h }
$c8=Cfg $r8; $c4=Cfg $r4; "REPLAYCFG q8: $(($c8.GetEnumerator()|%{"$($_.Key)=$($_.Value)"}) -join ' ')  q4: $(($c4.GetEnumerator()|%{"$($_.Key)=$($_.Value)"}) -join ' ')" | Add-Content $L
"$(Get-Date -f s) MILESTONE e2e replay-tuned vs cold-tuned" | Add-Content $L
foreach($run in @(@("cold-tuned",@{}),@("replay-tuned",$c8),@("q4cls cold-tuned",@{SMOL_CLS="q4"}),@("q4cls replay-tuned",($c4+@{SMOL_CLS="q4"})))){
  Get-ChildItem Env: | ? Name -match '^SMOL_(XS\d|CLS)$' | % { Remove-Item "Env:$($_.Name)" }; foreach($e in $run[1].GetEnumerator()){ Set-Item "Env:$($e.Key)" $e.Value }
  foreach($ids in "8530,128","65,42,14"){ $o=(& .\out\smol_sm11.exe $M $ids 32 both 2>&1) -join "`n"; $t=($o -split "`n" | Select-String "gpu_tps|match|tok_lat|cu err" | % { $_.Line -replace ', work chunks.*','' }) -join " | "; "E2R [$($run[0])] prompt=$ids $t" | Add-Content $L } }
"$(Get-Date -f s) MILESTONE job10 done" | Add-Content $L
