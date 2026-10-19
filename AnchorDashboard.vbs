' Anchor Dashboard launcher (silent, no console flash).
' The Anchor server runs persistently under the NSSM service "anchor".
' This launcher ONLY opens the dashboard URL in the default browser — it must
' never start a server (that would spawn a duplicate squatting port 8777).
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "http://localhost:8777", 1, False
