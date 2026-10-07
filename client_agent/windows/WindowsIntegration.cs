// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

namespace HeimserverClient {
    public static class WindowsIntegration {
        const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        const string RunName = "HeimserverManagerClient";
        public static string InstallDirectory { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "HeimserverManagerClient", Release.Version); } }
        public static string InstalledExe { get { return Path.Combine(InstallDirectory, "HeimserverManagerClient.exe"); } }
        public static string Shortcut { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Heimserver Manager Client.lnk"); } }
        public static bool Autostart {
            get { using (var key = Registry.CurrentUser.OpenSubKey(RunKey)) return key != null && key.GetValue(RunName) != null; }
        }
        public static void SetAutostart(bool enabled) {
            using (var key = Registry.CurrentUser.CreateSubKey(RunKey)) {
                if (enabled) {
                    if (!File.Exists(InstalledExe)) throw new ClientError(I18n.Tr("Bitte zuerst für diesen Benutzer installieren."));
                    var command = "\"" + InstalledExe + "\" --background --autostart";
                    if (command.Length > 260) throw new ClientError(I18n.Tr("Benutzerpfad zu lang für den Windows-Autostart."));
                    key.SetValue(RunName, command, RegistryValueKind.String);
                } else key.DeleteValue(RunName, false);
            }
        }
        public static void Install() {
            Directory.CreateDirectory(InstallDirectory);
            if (!String.Equals(Path.GetFullPath(Application.ExecutablePath), Path.GetFullPath(InstalledExe), StringComparison.OrdinalIgnoreCase)) {
                // Never silently replace a different executable with the same published version.
                if (File.Exists(InstalledExe)) {
                    if (!EqualFiles(Application.ExecutablePath, InstalledExe)) throw new ClientError(I18n.Tr("Anderer Stand dieser Version bereits installiert. Neue Versionsnummer verwenden."));
                } else File.Copy(Application.ExecutablePath, InstalledExe, false);
            }
            object shell = null, link = null;
            try {
                var type = Type.GetTypeFromProgID("WScript.Shell");
                shell = Activator.CreateInstance(type);
                Directory.CreateDirectory(Path.GetDirectoryName(Shortcut));
                link = type.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { Shortcut });
                var linkType = link.GetType();
                linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { InstalledExe });
                linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { InstallDirectory });
                linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "Heimserver Manager Client" });
                linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
            } finally {
                if (link != null && Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link);
                if (shell != null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell);
            }
        }
        static bool EqualFiles(string a, string b) {
            using (var hash = System.Security.Cryptography.SHA256.Create())
            using (var first = File.OpenRead(a))
            using (var second = File.OpenRead(b))
                return Convert.ToBase64String(hash.ComputeHash(first)) == Convert.ToBase64String(hash.ComputeHash(second));
        }
        public static void RemoveIntegration() {
            SetAutostart(false);
            if (File.Exists(Shortcut)) File.Delete(Shortcut);
            // Running EXE cannot be removed safely here. User may delete the named Programs folder after exit.
        }
    }
}
