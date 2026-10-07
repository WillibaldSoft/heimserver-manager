// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Forms;
using HeimserverClient;

static class Tests {
    static int count;
    static void Check(bool condition, string name) { if (!condition) throw new Exception(name); count++; Console.WriteLine("OK: " + name); }
    [STAThread] static int Main(string[] args) {
        try {
            if (args[0] == "gui") {
                Application.EnableVisualStyles();
                using (var form = new ClientForm(false, null, true))
                using (var timer = new System.Windows.Forms.Timer { Interval = 10000 }) {
                    bool ok = false;
                    timer.Tick += (s,e) => { timer.Stop(); ok = form.Visible && form.FieldCount == 9 && form.TrayVisible; if (args.Length > 1) { using (var bitmap = new System.Drawing.Bitmap(form.Width, form.Height)) { form.DrawToBitmap(bitmap, new System.Drawing.Rectangle(0, 0, form.Width, form.Height)); bitmap.Save(args[1]); } } form.Exit(); };
                    timer.Start(); Application.Run(form);
                    Check(ok, "Fenster, neun Einstellungen, Statussymbol und Beenden");
                }
                return 0;
            }
            var config = new Config { SERVER_URL = args[0], TOKEN = "test-token", CLIENT_NAME = "Test Client" }.Validate();
            Check(config.CLIENT_MODE == "without_server", "Neuer Client weckt nicht automatisch");
            foreach (string mode in new [] { "with_server", "without_server", "wake_on_access" }) {
                var c = config.Copy(); c.CLIENT_MODE = mode;
                Check(Payload.For(c).server_required == (mode == "with_server"), "Heartbeat-Bedarf: " + mode);
            }
            foreach (string invalid in new [] { "file:///etc/passwd", "http://" + "user" + ":" + "pass" + "@localhost", "http://localhost/?token=bad", "http://localhost/#fragment" }) {
                bool rejected = false; var c = config.Copy(); c.SERVER_URL = invalid;
                try { c.Validate(); } catch (ClientError) { rejected = true; }
                Check(rejected, "Ungültige Manager-Adresse abgelehnt");
            }
            var wol = Protocol.MagicPacket("01:02:03:04:05:06");
            Check(wol.Length == 102 && wol.Take(6).All(x => x == 255) && wol.Skip(6).Where((x,i) => x != i % 6 + 1).Count() == 0, "Wake-on-LAN Magic Packet");
            string file = Path.GetTempFileName();
            try {
                File.WriteAllBytes(file, Json.Write(new Profile { format = "heimserver-manager-client", version = 1, config = config }));
                Check(Json.Import(file).TOKEN == "test-token", "Gemeinsames JSON-Profil importieren");
                File.WriteAllText(file, "{}"); bool rejected = false;
                try { Json.Import(file); } catch (ClientError) { rejected = true; }
                Check(rejected, "Unvollständiges Profil abgelehnt");
            } finally { File.Delete(file); }
            Protocol.Health(config, CancellationToken.None).GetAwaiter().GetResult();
            Protocol.Heartbeat(config, CancellationToken.None).GetAwaiter().GetResult();
            config.CLIENT_MODE = "with_server";
            Protocol.Heartbeat(config, CancellationToken.None).GetAwaiter().GetResult();
            Protocol.Need(config, CancellationToken.None).GetAwaiter().GetResult();
            Protocol.Release(config, CancellationToken.None).GetAwaiter().GetResult();
            config.WAKE_METHOD = "recover"; config.IPMI_RECOVER_URL = args[0] + "/recover";
            Protocol.Wake(config.Validate(), CancellationToken.None).GetAwaiter().GetResult();
            Check(true, "Health, Heartbeat, Bedarf, Freigabe und Recovery ohne Fehler");
            foreach (string endpoint in new [] { "/redirect", "/unauthorized" }) {
                bool rejected = false;
                try { Protocol.Request(args[0] + endpoint, "GET", config.TOKEN, null, 2, CancellationToken.None).GetAwaiter().GetResult(); }
                catch (ClientError ex) { rejected = !ex.Message.Contains(config.TOKEN); }
                Check(rejected, "HTTP-Fehler ohne Token und ohne Redirect: " + endpoint);
            }
            using (var cancel = new CancellationTokenSource(200)) {
                bool cancelled = false;
                try { Protocol.Request(args[0] + "/slow", "GET", null, null, 10, cancel.Token).GetAwaiter().GetResult(); }
                catch (OperationCanceledException) { cancelled = true; }
                Check(cancelled, "Laufender Netzwerkaufruf abbrechbar");
            }
            Console.WriteLine(count + " Prüfungen erfolgreich"); return 0;
        } catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
}
