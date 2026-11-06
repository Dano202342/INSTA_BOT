Set WshShell = CreateObject("WScript.Shell")
dirPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = dirPath
WshShell.Run "cmd.exe /c """ & dirPath & "\run_24_7.bat""", 0, False
Set WshShell = Nothing
