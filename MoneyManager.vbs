Option Explicit

Const APP_FOLDER_NAME = "MoneyManagerLauncher"
Const CONFIG_FILE_NAME = "config.json"

Dim fso, shell, projectDir, pythonCommand, command, scriptDir
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = ResolveExplicitProjectDir()
If projectDir = "" Then projectDir = ResolveCandidateProjectDir(scriptDir)
If projectDir = "" Then projectDir = ResolveCandidateProjectDir(shell.CurrentDirectory)
If projectDir = "" Then projectDir = ResolveCandidateProjectDir(shell.ExpandEnvironmentStrings("%MONEY_MANAGER_PROJECT_DIR%"))
If projectDir = "" Then projectDir = ReadRememberedProjectDir()
If projectDir = "" Then projectDir = BrowseForProjectDir()

If projectDir = "" Then
    MsgBox "Money Manager was not started because no project folder was selected.", vbInformation, "Money Manager"
    WScript.Quit 1
End If

pythonCommand = FindPythonCommand()
If pythonCommand = "" Then
    MsgBox "Python 3 was not found." & vbCrLf & vbCrLf & _
           "Install Python from python.org and enable the Python launcher/PATH option, then run this launcher again." & vbCrLf & vbCrLf & _
           "For diagnostics, use MoneyManagerConsole.bat.", _
           vbCritical, "Money Manager launcher error"
    WScript.Quit 1
End If

command = pythonCommand & " " & Quote(projectDir & "\launcher.py") & _
          " --hidden --project-dir " & Quote(projectDir)

' Window style 0 keeps py/python and every inherited console hidden. launcher.py
' subsequently uses pythonw.exe and CREATE_NO_WINDOW for the server/helpers.
shell.Run command, 0, False
WScript.Quit 0

Function ResolveExplicitProjectDir()
    Dim i, value
    ResolveExplicitProjectDir = ""
    For i = 0 To WScript.Arguments.Count - 1
        value = CStr(WScript.Arguments(i))
        If LCase(Left(value, 14)) = "--project-dir=" Then
            value = Mid(value, 15)
            If IsProjectDir(value) Then ResolveExplicitProjectDir = fso.GetAbsolutePathName(value)
            Exit Function
        End If
        If LCase(value) = "--project-dir" And i + 1 < WScript.Arguments.Count Then
            value = CStr(WScript.Arguments(i + 1))
            If IsProjectDir(value) Then ResolveExplicitProjectDir = fso.GetAbsolutePathName(value)
            Exit Function
        End If
    Next
End Function

Function ResolveCandidateProjectDir(startDir)
    Dim currentDir, parentDir
    ResolveCandidateProjectDir = ""
    If Trim(CStr(startDir)) = "" Then Exit Function
    On Error Resume Next
    currentDir = fso.GetAbsolutePathName(Trim(CStr(startDir)))
    If Err.Number <> 0 Then
        Err.Clear
        On Error GoTo 0
        Exit Function
    End If
    On Error GoTo 0

    Do While currentDir <> ""
        If IsProjectDir(currentDir) Then
            ResolveCandidateProjectDir = currentDir
            Exit Function
        End If
        parentDir = fso.GetParentFolderName(currentDir)
        If LCase(parentDir) = LCase(currentDir) Then Exit Do
        currentDir = parentDir
    Loop
End Function

Function IsProjectDir(pathValue)
    Dim candidate
    IsProjectDir = False
    candidate = Trim(CStr(pathValue))
    If candidate = "" Then Exit Function
    On Error Resume Next
    candidate = fso.GetAbsolutePathName(candidate)
    If Err.Number <> 0 Then
        Err.Clear
        On Error GoTo 0
        Exit Function
    End If
    On Error GoTo 0
    IsProjectDir = fso.FolderExists(candidate) And _
                   fso.FileExists(candidate & "\launcher.py") And _
                   fso.FileExists(candidate & "\run_money_manager.py") And _
                   fso.FileExists(candidate & "\requirements.txt") And _
                   fso.FileExists(candidate & "\money_manager\app.py")
End Function

Function ReadRememberedProjectDir()
    Dim baseDir, configPath, stream, content, re, matches, rawValue
    ReadRememberedProjectDir = ""
    baseDir = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
    If baseDir = "%LOCALAPPDATA%" Or Trim(baseDir) = "" Then
        baseDir = shell.ExpandEnvironmentStrings("%APPDATA%")
    End If
    If baseDir = "%APPDATA%" Or Trim(baseDir) = "" Then Exit Function
    configPath = baseDir & "\" & APP_FOLDER_NAME & "\" & CONFIG_FILE_NAME
    If Not fso.FileExists(configPath) Then Exit Function

    On Error Resume Next
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2
    stream.Charset = "utf-8"
    stream.Open
    stream.LoadFromFile configPath
    content = stream.ReadText
    stream.Close
    If Err.Number <> 0 Then
        Err.Clear
        On Error GoTo 0
        Exit Function
    End If
    On Error GoTo 0

    Set re = New RegExp
    re.Pattern = """project_dir""\s*:\s*""([^""]*)"""
    re.IgnoreCase = True
    re.Global = False
    Set matches = re.Execute(content)
    If matches.Count = 0 Then Exit Function
    rawValue = matches(0).SubMatches(0)
    rawValue = Replace(rawValue, "\" & Chr(34), Chr(34))
    rawValue = Replace(rawValue, "\/", "/")
    rawValue = Replace(rawValue, "\\", "\")
    If IsProjectDir(rawValue) Then ReadRememberedProjectDir = fso.GetAbsolutePathName(rawValue)
End Function

Function BrowseForProjectDir()
    Dim app, folder, selected
    BrowseForProjectDir = ""
    Set app = CreateObject("Shell.Application")
    Do
        Set folder = app.BrowseForFolder(0, _
            "Select the Money Manager folder containing launcher.py, run_money_manager.py, requirements.txt, and the money_manager folder.", _
            &H41, 17)
        If folder Is Nothing Then Exit Function
        On Error Resume Next
        selected = folder.Self.Path
        On Error GoTo 0
        If IsProjectDir(selected) Then
            BrowseForProjectDir = fso.GetAbsolutePathName(selected)
            Exit Function
        End If
        MsgBox "The selected folder is not a valid Money Manager repository.", vbExclamation, "Money Manager"
    Loop
End Function

Function FindPythonCommand()
    Dim found
    FindPythonCommand = ""
    found = FindOnPath("pyw.exe")
    If found <> "" Then
        FindPythonCommand = Quote(found) & " -3"
        Exit Function
    End If
    found = FindOnPath("pythonw.exe")
    If found <> "" Then
        FindPythonCommand = Quote(found)
        Exit Function
    End If
    found = FindOnPath("py.exe")
    If found <> "" Then
        FindPythonCommand = Quote(found) & " -3"
        Exit Function
    End If
    found = FindOnPath("python.exe")
    If found <> "" Then FindPythonCommand = Quote(found)
End Function

Function FindOnPath(executableName)
    Dim pathValue, folders, folder, candidate, windowsDir, localPrograms, pythonRoot, subfolder
    FindOnPath = ""
    pathValue = shell.ExpandEnvironmentStrings("%PATH%")
    folders = Split(pathValue, ";")
    For Each folder In folders
        folder = Trim(Replace(CStr(folder), """", ""))
        If folder <> "" Then
            candidate = fso.BuildPath(folder, executableName)
            If fso.FileExists(candidate) Then
                FindOnPath = candidate
                Exit Function
            End If
        End If
    Next

    windowsDir = shell.ExpandEnvironmentStrings("%WINDIR%")
    If windowsDir <> "%WINDIR%" Then
        candidate = fso.BuildPath(windowsDir, executableName)
        If fso.FileExists(candidate) Then
            FindOnPath = candidate
            Exit Function
        End If
    End If

    localPrograms = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
    If fso.FolderExists(localPrograms) Then
        Set pythonRoot = fso.GetFolder(localPrograms)
        For Each subfolder In pythonRoot.SubFolders
            candidate = fso.BuildPath(subfolder.Path, executableName)
            If fso.FileExists(candidate) Then
                FindOnPath = candidate
                Exit Function
            End If
        Next
    End If
End Function

Function Quote(value)
    Quote = Chr(34) & CStr(value) & Chr(34)
End Function
