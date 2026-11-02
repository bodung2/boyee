' Run a scripts\*.bat without a console window (for jobs that run often, e.g. every hour).
' Usage (Task Scheduler action): wscript.exe "...\scripts\run_hidden.vbs" "...\scripts\job.bat" [args...]
' Waits for the job and returns its exit code, so Task Scheduler still shows success/failure.
Option Explicit
Dim sh, cmd, i, a
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count = 0 Then WScript.Quit 2
cmd = """" & WScript.Arguments(0) & """"
For i = 1 To WScript.Arguments.Count - 1
    a = WScript.Arguments(i)
    If InStr(a, " ") > 0 Then a = """" & a & """"
    cmd = cmd & " " & a
Next
WScript.Quit sh.Run(cmd, 0, True)
