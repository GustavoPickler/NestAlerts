Option Explicit
Dim WshShell, fso, projectPath, batPath, logPath, logFile

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectPath = "C:\Users\gustavo.pickler\Documents\Scripts\NestAlerts"
batPath     = projectPath & "\scripts\run_alerts_once.bat"
logPath     = projectPath & "\logs\vbs_exec.log"

If Not fso.FolderExists(projectPath & "\logs") Then fso.CreateFolder(projectPath & "\logs")
Set logFile = fso.OpenTextFile(logPath, 8, True)
logFile.WriteLine Now & " - VBScript start (bat)"
logFile.Close

If Not fso.FileExists(batPath) Then
  Set logFile = fso.OpenTextFile(logPath, 8, True)
  logFile.WriteLine Now & " - ERRO: bat nao encontrado: " & batPath
  logFile.Close
  WScript.Quit 1
End If

WshShell.CurrentDirectory = projectPath
WshShell.Run """" & batPath & """", 0, False

Set logFile = fso.OpenTextFile(logPath, 8, True)
logFile.WriteLine Now & " - Disparado: " & batPath
logFile.Close
