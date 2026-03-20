Set-Location -Path "C:\Users\a\OneDrive\Documents\git repo\spotify-ytmusic-sync\backend"
Start-Process -FilePath "pip" -ArgumentList "install -r requirements.txt --quiet" -Wait -WindowStyle Hidden -RedirectStandardOutput "pip_log.txt" -RedirectStandardError "pip_err.txt"
Start-Process -FilePath "python" -ArgumentList "-m uvicorn main:app --host 127.0.0.1 --port 8000" -WindowStyle Hidden -RedirectStandardOutput "app_log.txt" -RedirectStandardError "app_err.txt"
