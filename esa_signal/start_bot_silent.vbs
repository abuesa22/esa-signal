Set WShell = CreateObject("WScript.Shell")
WShell.CurrentDirectory = "C:\Users\Esa\OneDrive\Desktop\esa signal\esa_signal"
WShell.Run Chr(34) & "C:\Users\Esa\AppData\Local\Programs\Python\Python311\python.exe" & Chr(34) & " watchdog.py", 0, False
