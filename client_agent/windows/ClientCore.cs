// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace HeimserverClient {
    public static class Release { public const string Version = "0.2.7"; }

    [DataContract]
    public class Config {
        [DataMember] public string SERVER_URL = "";
        [DataMember] public string IPMI_RECOVER_URL = "";
        [DataMember] public string TOKEN = "";
        [DataMember] public string CLIENT_NAME = Environment.MachineName;
        [DataMember] public string CLIENT_MAC = "";
        [DataMember] public string CLIENT_MODE = "without_server";
        [DataMember] public string WAKE_METHOD = "none";
        [DataMember] public string SERVER_MAC = "";
        [DataMember] public string WAKE_TIMEOUT = "40";
        public Config Copy() { return (Config)MemberwiseClone(); }
        public Config Validate() {
            var c = Copy();
            foreach (var field in typeof(Config).GetFields()) {
                var value = (string)field.GetValue(c) ?? "";
                if (value.Length > 2048 || value.Any(Char.IsControl)) throw new ClientError(I18n.Tr("Ungültige Eingabe: ") + field.Name);
                field.SetValue(c, value.Trim());
            }
            if (c.CLIENT_MODE == "auto" || c.CLIENT_MODE == "connected") c.CLIENT_MODE = "with_server";
            if (c.CLIENT_MODE == "disabled" || c.CLIENT_MODE == "release-only") c.CLIENT_MODE = "without_server";
            Address(c.SERVER_URL, false);
            Address(c.IPMI_RECOVER_URL, true);
            if (c.TOKEN.Length == 0 || c.CLIENT_NAME.Length == 0) throw new ClientError(I18n.Tr("Client-Name und Agenten-Token fehlen."));
            foreach (var mac in new [] { c.CLIENT_MAC, c.SERVER_MAC })
                if (mac.Length != 0 && !Regex.IsMatch(mac, "^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")) throw new ClientError(I18n.Tr("MAC-Adresse im Format aa:bb:cc:dd:ee:ff eingeben."));
            if (!new [] {"with_server", "without_server", "wake_on_access"}.Contains(c.CLIENT_MODE)) throw new ClientError(I18n.Tr("Ungültiger Betriebsmodus."));
            if (!new [] {"none", "wol", "recover", "both"}.Contains(c.WAKE_METHOD)) throw new ClientError(I18n.Tr("Ungültige Weckmethode."));
            if ((c.WAKE_METHOD == "wol" || c.WAKE_METHOD == "both") && c.SERVER_MAC.Length == 0) throw new ClientError(I18n.Tr("Server-MAC für Wake-on-LAN fehlt."));
            if ((c.WAKE_METHOD == "recover" || c.WAKE_METHOD == "both") && c.IPMI_RECOVER_URL.Length == 0) throw new ClientError(I18n.Tr("Recovery-Adresse fehlt."));
            int timeout;
            if (!Int32.TryParse(c.WAKE_TIMEOUT, out timeout) || timeout < 1 || timeout > 300) throw new ClientError(I18n.Tr("Recovery-Timeout: 1 bis 300 Sekunden."));
            c.SERVER_URL = c.SERVER_URL.TrimEnd('/');
            return c;
        }
        static void Address(string value, bool optional) {
            if (optional && value.Length == 0) return;
            Uri uri;
            if (!Uri.TryCreate(value, UriKind.Absolute, out uri) || (uri.Scheme != "http" && uri.Scheme != "https") || String.IsNullOrEmpty(uri.Host) || uri.UserInfo.Length != 0 || uri.Fragment.Length != 0 || value.Any(Char.IsWhiteSpace))
                throw new ClientError(I18n.Tr("Gültige HTTP(S)-Adresse ohne eingebettete Zugangsdaten eingeben."));
            // API endpoints must be appended to a path, never to an existing query string.
            if (!optional && uri.Query.Length != 0) throw new ClientError(I18n.Tr("Manager-Adresse ohne Abfrageparameter eingeben."));
        }
    }

    public class ClientError : Exception { public ClientError(string text) : base(text) {} }
    [DataContract] public class Profile {
        [DataMember] public string format;
        [DataMember] public int version;
        [DataMember] public Config config;
        [DataMember] public HttpsProfile https;
    }
    [DataContract] public class Saved {
        [DataMember] public int version = 1;
        [DataMember] public bool enabled;
        [DataMember] public Config config = new Config();
    }
    public static class Json {
        public static byte[] Write<T>(T value) {
            using (var stream = new MemoryStream()) {
                new DataContractJsonSerializer(typeof(T)).WriteObject(stream, value);
                return stream.ToArray();
            }
        }
        public static T Read<T>(byte[] data) {
            if (data.Length > 65536) throw new ClientError(I18n.Tr("Datei ist zu groß (maximal 64 KB)."));
            using (var stream = new MemoryStream(data)) return (T)new DataContractJsonSerializer(typeof(T)).ReadObject(stream);
        }
        public static Config Import(string path) {
            if (new FileInfo(path).Length > 65536) throw new ClientError(I18n.Tr("Profil ist zu groß."));
            Profile profile;
            try { profile = Read<Profile>(File.ReadAllBytes(path)); }
            catch { throw new ClientError(I18n.Tr("Ungültige JSON-Profildatei.")); }
            if (profile == null || profile.format != "heimserver-manager-client" || profile.version != 1 || profile.config == null) throw new ClientError(I18n.Tr("Kein unterstütztes Client-Profil."));
            return profile.config.Validate();
        }
    }
    public static class Storage {
        public static string Root { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HeimserverManagerClient"); } }
        public static string ConfigPath { get { return Path.Combine(Root, "config.dat"); } }
        static readonly byte[] Entropy = Encoding.UTF8.GetBytes("HeimserverManagerClient-profile-v1");
        public static void Prepare() {
            Directory.CreateDirectory(Root);
            var acl = new DirectorySecurity();
            acl.SetAccessRuleProtection(true, false);
            foreach (var sid in new [] { WindowsIdentity.GetCurrent().User, new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null) })
                acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
            Directory.SetAccessControl(Root, acl);
        }
        public static Saved Load() {
            if (!File.Exists(ConfigPath)) return new Saved();
            try {
                if (new FileInfo(ConfigPath).Length > 131072) throw new ClientError(I18n.Tr("Konfiguration zu groß."));
                var saved = Json.Read<Saved>(ProtectedData.Unprotect(File.ReadAllBytes(ConfigPath), Entropy, DataProtectionScope.CurrentUser));
                if (saved.version != 1) throw new ClientError(I18n.Tr("Unbekannte Konfigurationsversion."));
                saved.config = saved.config.Validate();
                return saved;
            } catch { throw new ClientError(I18n.Tr("Gespeicherte Konfiguration nicht lesbar. Nur derselbe Windows-Benutzer kann sie entschlüsseln. Vorhandene Datei bleibt erhalten.")); }
        }
        public static void Save(Saved saved) {
            saved.config = saved.config.Validate();
            Prepare();
            var encrypted = ProtectedData.Protect(Json.Write(saved), Entropy, DataProtectionScope.CurrentUser);
            var temp = Path.Combine(Root, Guid.NewGuid().ToString("N") + ".tmp");
            try {
                using (var stream = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { stream.Write(encrypted, 0, encrypted.Length); stream.Flush(true); }
                if (File.Exists(ConfigPath)) File.Replace(temp, ConfigPath, ConfigPath + ".bak");
                else File.Move(temp, ConfigPath);
            } finally { if (File.Exists(temp)) File.Delete(temp); }
        }
        public static void Log(string safeMessage) {
            // Callers supply fixed messages/status codes only, never URLs, tokens or raw exceptions.
            try {
                var path = Path.Combine(Root, "client.log");
                if (!Directory.Exists(Root)) return;
                if (File.Exists(path) && new FileInfo(path).Length > 131072) File.Delete(path);
                File.AppendAllText(path, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + safeMessage + Environment.NewLine);
            } catch { }
        }
    }

    [DataContract] public class Payload {
        [DataMember] public string hostname = Environment.MachineName;
        [DataMember] public string client;
        [DataMember] public string mac;
        [DataMember] public string mode;
        [DataMember] public string reason;
        [DataMember] public string version = "windows-" + Release.Version;
        [DataMember] public bool server_required;
        public static Payload For(Config c) { return new Payload { client = c.CLIENT_NAME, mac = c.CLIENT_MAC, mode = c.CLIENT_MODE, reason = c.CLIENT_MODE == "with_server" ? "auto" : c.CLIENT_MODE, server_required = c.CLIENT_MODE == "with_server" }; }
    }
    public static class Protocol {
        public static async Task Request(string url, string method, string token, byte[] payload, int timeout, CancellationToken cancel) {
            await Task.Run(() => {
                cancel.ThrowIfCancellationRequested();
                var request = (HttpWebRequest)WebRequest.Create(url);
                request.Method = method; request.AllowAutoRedirect = false;
                request.Timeout = timeout * 1000; request.ReadWriteTimeout = timeout * 1000;
                request.UserAgent = "HeimserverManagerClient/" + HeimserverClient.Release.Version;
                if (!String.IsNullOrEmpty(token)) { request.Headers[HttpRequestHeader.Authorization] = "Bearer " + token; DeviceBinding.Headers(request); }
                using (cancel.Register(request.Abort)) {
                    try {
                        if (payload != null) {
                            request.ContentType = "application/json"; request.ContentLength = payload.Length;
                            using (var stream = request.GetRequestStream()) stream.Write(payload, 0, payload.Length);
                        } else if (method == "POST") request.ContentLength = 0;
                        using (var response = (HttpWebResponse)request.GetResponse()) {
                            int status = (int)response.StatusCode;
                            if (status < 200 || status >= 300) throw new ClientError("HTTP " + status + I18n.Tr(": Ziel antwortet nicht erfolgreich. Weiterleitungen werden nicht verfolgt."));
                        }
                    } catch (WebException error) {
                        cancel.ThrowIfCancellationRequested();
                        using (var response = error.Response as HttpWebResponse) {
                            if (response != null) {
                                int code = (int)response.StatusCode;
                                throw new ClientError(code == 401 || code == 403 ? I18n.Tr("Anmeldung abgelehnt: Agenten-Token prüfen (HTTP ") + code + ")." : I18n.Tr("Server meldet HTTP ") + code + ".");
                            }
                        }
                        throw new ClientError(I18n.Tr("Verbindung fehlgeschlagen oder Zeitlimit erreicht. Adresse, Netzwerk und Zertifikat prüfen."));
                    }
                }
            }, cancel);
        }
        public static Task Status(Config c, CancellationToken ct) { return Request(c.SERVER_URL + "/api/clients/status", "GET", c.TOKEN, null, 4, ct); }
        public static Task Health(Config c, CancellationToken ct) { return Request(c.SERVER_URL + "/api/health", "GET", null, null, 4, ct); }
        public static Task Heartbeat(Config c, CancellationToken ct) { return Request(c.SERVER_URL + "/api/clients/heartbeat", "POST", c.TOKEN, Json.Write(Payload.For(c)), 10, ct); }
        public static Task Release(Config c, CancellationToken ct) { return Request(c.SERVER_URL + "/api/clients/release-server", "POST", c.TOKEN, null, 15, ct); }
        public static Task Need(Config c, CancellationToken ct) {
            var payload = Payload.For(c); payload.reason = "manual"; payload.server_required = true;
            return Request(c.SERVER_URL + "/api/clients/need-server", "POST", c.TOKEN, Json.Write(payload), 15, ct);
        }
        public static byte[] MagicPacket(string mac) {
            var bytes = mac.Split(':').Select(x => Convert.ToByte(x, 16)).ToArray();
            if (bytes.Length != 6) throw new ClientError(I18n.Tr("Ungültige Server-MAC."));
            var packet = new byte[102];
            for (int i = 0; i < 6; i++) packet[i] = 255;
            for (int i = 0; i < 16; i++) Array.Copy(bytes, 0, packet, 6 + i * 6, 6);
            return packet;
        }
        public static async Task Wake(Config c, CancellationToken ct) {
            Exception recoverError = null;
            if (c.WAKE_METHOD == "recover" || c.WAKE_METHOD == "both") {
                try { await Request(c.IPMI_RECOVER_URL, "GET", null, null, Int32.Parse(c.WAKE_TIMEOUT), ct); }
                catch (ClientError ex) { recoverError = ex; }
            }
            ct.ThrowIfCancellationRequested();
            if (c.WAKE_METHOD == "wol" || c.WAKE_METHOD == "both") {
                var packet = MagicPacket(c.SERVER_MAC);
                using (var udp = new UdpClient()) { udp.EnableBroadcast = true; await udp.SendAsync(packet, packet.Length, new IPEndPoint(IPAddress.Broadcast, 9)); }
            }
            if (recoverError != null) throw new ClientError(c.WAKE_METHOD == "both" ? I18n.Tr("Recovery-Aufruf fehlgeschlagen; Wake-on-LAN wurde trotzdem gesendet. Erreichbarkeit prüfen.") : recoverError.Message);
        }
        public static async Task Wait(Config c, CancellationToken ct) {
            var until = DateTime.UtcNow.AddMinutes(10);
            while (DateTime.UtcNow < until) {
                ct.ThrowIfCancellationRequested();
                try { await Health(c, ct); return; } catch (ClientError) { }
                await Task.Delay(5000, ct);
            }
            throw new ClientError(I18n.Tr("Server nach zehn Minuten noch nicht erreichbar."));
        }
        public static async Task Action(Config c, string action, CancellationToken ct) {
            switch (action) {
                case "wake": await Wake(c, ct); break;
                case "need": await Need(c, ct); break;
                case "release": await Release(c, ct); break;
                case "connect": await Wake(c, ct); await Wait(c, ct); await Need(c, ct); break;
                case "access": await Wake(c, ct); await Wait(c, ct); break;
                default: throw new ClientError(I18n.Tr("Unbekannte Aktion."));
            }
        }
    }
}
