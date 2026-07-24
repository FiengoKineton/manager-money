Option Explicit
Dim fso, shell, projectDir, launcherPath, iconPath, desktopPath, shortcutPath, shortcut
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcherPath = projectDir & "\MoneyManager.vbs"
iconPath = projectDir & "\static\icons\money-manager.ico"

If Not fso.FileExists(launcherPath) Or Not fso.FileExists(iconPath) Then
    MsgBox "MoneyManager.vbs or the Money Manager icon was not found beside this script.", vbCritical, "Money Manager shortcut"
    WScript.Quit 1
End If

desktopPath = shell.SpecialFolders("Desktop")
shortcutPath = desktopPath & "\Money Manager.lnk"
Set shortcut = shell.CreateShortcut(shortcutPath)
shortcut.TargetPath = shell.ExpandEnvironmentStrings("%WINDIR%\System32\wscript.exe")
shortcut.Arguments = """" & launcherPath & """"
shortcut.WorkingDirectory = projectDir
shortcut.IconLocation = iconPath & ",0"
shortcut.Description = "Open Money Manager as a local desktop application"
shortcut.WindowStyle = 1
shortcut.Save
MsgBox "Desktop shortcut created:" & vbCrLf & shortcutPath, vbInformation, "Money Manager"
