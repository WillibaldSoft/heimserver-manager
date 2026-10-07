// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Security.Principal;
using System.Threading;
using System.Windows.Forms;
using System.Reflection;
[assembly: AssemblyTitle("Heimserver Manager Client")]
[assembly: AssemblyDescription("Windows-Client: Serverbedarf, Wake-on-LAN, Recovery und Statussymbol")]
[assembly: AssemblyProduct("Heimserver Manager Client")]
[assembly: AssemblyVersion("0.2.7.0")]
[assembly: AssemblyFileVersion("0.2.7.0")]
namespace HeimserverClient {
    static class Program {
        [STAThread] static void Main(string[] args) {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            Application.ThreadException += (s,e) => MessageBox.Show(I18n.Tr("Oberflächenfehler. Client beenden und erneut öffnen."), "Heimserver Manager Client");
            if(args.Length==2 && (args[0]=="--https-install"||args[0]=="--https-remove")) {
                try { Extras.ApplyHttps(args[1],args[0]=="--https-remove"); Environment.ExitCode=0; }
                catch(Exception ex){MessageBox.Show(ex.Message,I18n.Tr("HTTPS-Einrichtung"));Environment.ExitCode=1;} return;
            }
            try {
                if (args.Contains("--autostart") && !File.Exists(Storage.ConfigPath)) return;
                string sid = WindowsIdentity.GetCurrent().User.Value;
                bool created;
                using (var mutex = new Mutex(true, @"Local\HeimserverManagerClient-" + sid, out created))
                using (var signal = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\HeimserverManagerClientOpen-" + sid)) {
                    if (!created) { if (!args.Contains("--autostart")) signal.Set(); return; }
                    try { Application.Run(new ClientForm(args.Contains("--background"), signal)); }
                    finally { mutex.ReleaseMutex(); }
                }
            } catch { MessageBox.Show(I18n.Tr("Client konnte nicht gestartet werden. Bitte als normaler Windows-Benutzer öffnen und .NET Framework 4.8 sowie Dateiberechtigungen prüfen."), "Heimserver Manager Client", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        }
    }
}
