@echo off
rem Collects KinectCam troubleshooting info into kinectcam-diagnose.txt on the Desktop.
set OUT=%USERPROFILE%\Desktop\kinectcam-diagnose.txt
echo Collecting KinectCam diagnostics... (about 10 seconds)
> "%OUT%" echo ===== KinectCam diagnostics %DATE% %TIME%
>>"%OUT%" ver
>>"%OUT%" echo PROCESSOR_ARCHITECTURE=%PROCESSOR_ARCHITECTURE% %PROCESSOR_IDENTIFIER%
>>"%OUT%" echo.
>>"%OUT%" echo ===== setup.log
type "C:\ProgramData\KinectCam\setup.log" >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo ===== KinectCam.log
type "%LOCALAPPDATA%\KinectCam\KinectCam.log" >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo ===== Kinect USB devices (VID_045E)
powershell -NoProfile -Command "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_045E' } | ForEach-Object { $d=$_; $p=Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName DEVPKEY_Device_DriverInfPath,DEVPKEY_Device_Service,DEVPKEY_Device_DriverProvider,DEVPKEY_Device_ProblemCode -ErrorAction SilentlyContinue; '{0} | {1} | status={2} | {3}' -f $d.FriendlyName,$d.InstanceId,$d.Status,(($p | ForEach-Object { $_.KeyName.Split('_')[-1] + '=' + $_.Data }) -join ' ') }" >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo ===== All present USB devices with problems
powershell -NoProfile -Command "Get-PnpDevice -PresentOnly | Where-Object { $_.Status -ne 'OK' -and $_.InstanceId -like 'USB*' } | Format-Table -AutoSize Status,FriendlyName,InstanceId | Out-String -Width 300" >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo ===== Driver packages from KinectCam
pnputil /enum-drivers >"%TEMP%\kc_drv.txt" 2>&1
powershell -NoProfile -Command "Select-String -Path $env:TEMP\kc_drv.txt -Pattern 'kinect_' -Context 1,4 | Out-String -Width 300" >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo ===== KinectCam certificates
powershell -NoProfile -Command "Get-ChildItem Cert:\LocalMachine\Root,Cert:\LocalMachine\TrustedPublisher | Where-Object Subject -like '*KinectCam*' | Format-Table -AutoSize PSParentPath,Subject,NotAfter | Out-String -Width 300" >>"%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo ===== Device install log (last KinectCam / VID_045E entries)
powershell -NoProfile -Command "$t=Get-Content $env:WINDIR\INF\setupapi.dev.log -Tail 4000; $hit=@(); for($i=0;$i -lt $t.Count;$i++){ if($t[$i] -match 'kinect_|VID_045E'){ $hit+=$i } }; if($hit.Count){ $s=[Math]::Max(0,$hit[-1]-120); $t[$s..$($t.Count-1)] | Select-Object -Last 160 }" >>"%OUT%" 2>&1
echo.
echo Done: %OUT%
echo Send that file to Claude.
pause
