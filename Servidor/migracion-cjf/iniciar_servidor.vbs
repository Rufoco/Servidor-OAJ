Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\Usuarios\acorreab\Documentos\Servidor\migracion-cjf"
WshShell.Run "pythonw.exe servidor.py", 0, False