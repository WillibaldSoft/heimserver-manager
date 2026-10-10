// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace HeimserverClient {
    public class Choice {
        public string Key; public string Label;
        public Choice(string key, string label) { Key = key; Label = label; }
        public override string ToString() { return Label; }
    }
    public sealed class ClientForm : Form {
        readonly Dictionary<string, Control> fields = new Dictionary<string, Control>();
        readonly Label status = new Label(), notice = new Label();
        readonly CheckBox autostart = new CheckBox();
        readonly NotifyIcon tray = new NotifyIcon();
        readonly TrayIcons icons = new TrayIcons();
        bool connecting, connected;
        readonly System.Windows.Forms.Timer offlineTimer = new System.Windows.Forms.Timer();
        readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        readonly EventWaitHandle openEvent;
        readonly bool testMode;
        Saved saved;
        bool hiddenStart, quitting, busy, polling, startupPending = true;
        DateTime lastPoll = DateTime.MinValue, lastBeat = DateTime.MinValue;
        CancellationTokenSource lifetime = new CancellationTokenSource();
        CancellationTokenSource actionCancel;
        int generation;
        public int FieldCount { get { return fields.Count; } }
        public bool TrayVisible { get { return tray.Visible; } }

        public ClientForm(bool background, EventWaitHandle signal, bool test = false) {
            testMode = test; openEvent = signal;
            Text = I18n.Tr("Heimserver Manager Client · Windows ") + Release.Version;
            Size = new Size(850, 800); MinimumSize = new Size(640, 540);
            StartPosition = FormStartPosition.CenterScreen; AutoScaleMode = AutoScaleMode.Dpi;
            Icon = SystemIcons.Application;
            string loadError = null;
            try { saved = test ? new Saved() : Storage.Load(); } catch (ClientError ex) { saved = new Saved(); loadError = ex.Message; }
            hiddenStart = background && !test && File.Exists(Storage.ConfigPath) && loadError == null;
            var outer = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 6, Padding = new Padding(14) };
            outer.RowStyles.Add(new RowStyle(SizeType.AutoSize)); outer.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            outer.RowStyles.Add(new RowStyle(SizeType.AutoSize)); outer.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            outer.RowStyles.Add(new RowStyle(SizeType.AutoSize)); outer.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            Controls.Add(outer);
            status.AutoSize = true; status.MaximumSize = new Size(780, 0); status.Text = I18n.Tr("Noch nicht eingerichtet"); outer.Controls.Add(status, 0, 0);
            var actions = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
            AddAction(actions, I18n.Tr("Server wecken"), "wake"); AddAction(actions, I18n.Tr("Server benötigt"), "need"); AddAction(actions, I18n.Tr("Server freigeben"), "release");
            AddAction(actions, I18n.Tr("Wecken und verbinden"), "connect"); AddAction(actions, I18n.Tr("Zugriff vorbereiten"), "access");
            Button(actions, I18n.Tr("Aktion abbrechen"), () => { if (actionCancel != null) actionCancel.Cancel(); });
            outer.Controls.Add(actions, 0, 1);
            var explanation = new Label { AutoSize = true, MaximumSize = new Size(780, 0), Text = I18n.Tr("Der Agent läuft in deiner Windows-Benutzersitzung. Fenster schließen lässt Symbol und Heartbeat aktiv. Einmalige Bedarf/Freigabe-Aktionen werden beim nächsten Heartbeat vom Betriebsmodus bestimmt. Zugriff vorbereiten überwacht keine Dateien und bindet keine Freigaben ein."), Margin = new Padding(3, 8, 3, 10) };
            outer.Controls.Add(explanation, 0, 2);
            var scroll = new Panel { AutoScroll = true, Dock = DockStyle.Fill };
            var grid = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2, Padding = new Padding(0, 0, 12, 0) };
            grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 40)); grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 60)); scroll.Controls.Add(grid); outer.Controls.Add(scroll, 0, 3);
            var host = new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Top };
            host.Controls.Add(new Label { Text=Environment.MachineName, AutoSize=true });
            var rename = new Button { Text=I18n.Tr("Hostname ändern …"), AutoSize=true };
            rename.Click+=(s,e)=>{if(MessageBox.Show(this,I18n.Tr("Windows-Computernamen ändern? Administratorrechte und anschließend ein Windows-Neustart können nötig sein. Zugriffe über den alten Namen müssen angepasst werden. Laufende Sicherungen zuerst abschließen."),"Hostname",MessageBoxButtons.OKCancel)==DialogResult.OK) System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"SystemPropertiesComputerName.exe")){UseShellExecute=true});};
            host.Controls.Add(rename);grid.Controls.Add(new Label{Text=I18n.Tr("Hostname dieses Rechners"),AutoSize=true},0,grid.RowCount);grid.Controls.Add(host,1,grid.RowCount++);
            Field(grid, "SERVER_URL", I18n.Tr("Manager-Adresse (http:// oder https://)"));
            Field(grid, "TOKEN", I18n.Tr("Agenten-Token"), true);
            Field(grid, "CLIENT_NAME", I18n.Tr("Client-Name")); Field(grid, "CLIENT_MAC", I18n.Tr("Client-MAC (optional)"));
            Combo(grid, "CLIENT_MODE", I18n.Tr("Betriebsmodus"), new [] { new Choice("without_server", I18n.Tr("Ohne Server starten")), new Choice("with_server", I18n.Tr("Mit Server starten / benötigt")), new Choice("wake_on_access", I18n.Tr("Nur auf ausdrücklichen Aufruf wecken")) });
            Combo(grid, "WAKE_METHOD", I18n.Tr("Weckmethode"), new [] { new Choice("none", I18n.Tr("Nicht wecken")), new Choice("wol", I18n.Tr("Wake-on-LAN")), new Choice("recover", I18n.Tr("Recovery-Dienst")), new Choice("both", I18n.Tr("Recovery und Wake-on-LAN")) });
            Field(grid, "IPMI_RECOVER_URL", I18n.Tr("Recovery-Adresse (optional)"), true); Field(grid, "SERVER_MAC", I18n.Tr("Server-MAC für Wake-on-LAN")); Field(grid, "WAKE_TIMEOUT", I18n.Tr("Recovery-Timeout (1–300 Sekunden)"));
            autostart.Text = I18n.Tr("Statussymbol bei Windows-Anmeldung starten"); autostart.AutoSize = true;
            autostart.Checked = !test && (WindowsIntegration.Autostart || !File.Exists(Storage.ConfigPath));
            grid.Controls.Add(autostart, 0, grid.RowCount++); grid.SetColumnSpan(autostart, 2);
            offlineTimer.Interval=60000;
            offlineTimer.Tick+=async (sender,args)=>{if(busy)return;try{var row=OfflineFiles.Due();if(row!=null){notice.Text=await Task.Run(()=>OfflineFiles.Sync(saved.config,row));}}catch(Exception error){notice.Text=error.Message;}};
            offlineTimer.Start();
            var buttons = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
            Button(buttons, I18n.Tr("Offline-Dateien"), () => { try { new OfflineForm(saved.config).ShowDialog(this); } catch(Exception ex){Say(ex.Message);} });
            Button(buttons, I18n.Tr("Eigene Backups / Wiederherstellung"), () => { try { new ExtrasForm(saved.config,false,null).ShowDialog(this); } catch(Exception ex){Say(ex.Message);} });
            Button(buttons, I18n.Tr("Privates HTTPS"), () => { try { new ExtrasForm(saved.config,true,url=>{fields["SERVER_URL"].Text=url;Save(null);}).ShowDialog(this); } catch(Exception ex){Say(ex.Message);} });
            Button(buttons, I18n.Tr("Server-Backup (Administrator)"), () => { try { if(MessageBox.Show(this,I18n.Tr("Server-Sicherungen sind ausschließlich für den Manager-Administrator. Im Browser mit dem Manager-Konto anmelden. Das Passwort wird nicht im Client gespeichert."),I18n.Tr("Server-Backup"),MessageBoxButtons.OKCancel)==DialogResult.OK) System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(saved.config.Validate().SERVER_URL+"/login?reauth=1&next=/backup"){UseShellExecute=true}); } catch(Exception ex){Say(ex.Message);} });
            Button(buttons, I18n.Tr("Benutzer & Gerät koppeln"), PairDevice);
            Button(buttons, I18n.Tr("Profil importieren (.json)"), Import);
            Button(buttons, I18n.Tr("Speichern"), () => Save(null));
            Button(buttons, I18n.Tr("Agent aktivieren"), ActivateAgent);
            Button(buttons, I18n.Tr("Agent deaktivieren"), DeactivateAgent);
            Button(buttons, I18n.Tr("Für Benutzer installieren"), Install);
            Button(buttons, I18n.Tr("Protokoll"), Logs);
            Button(buttons, I18n.Tr("Status aktualisieren"), () => { lastPoll = DateTime.MinValue; lastBeat = DateTime.MinValue; });
            Button(buttons, I18n.Tr("Autostart / Startmenü entfernen"), Remove);
            outer.Controls.Add(buttons, 0, 4);
            notice.AutoSize = true; notice.MaximumSize = new Size(780, 0); notice.Text = loadError ?? I18n.Tr("JSON-Profil aus dem Manager importieren, prüfen und Agent aktivieren. Kein Administrator erforderlich."); outer.Controls.Add(notice, 0, 5);
            Fill(saved.config);
            var menu = new ContextMenuStrip();
            menu.Items.Add(I18n.Tr("Öffnen / Einstellungen"), null, (s,e) => OpenWindow());
            foreach (var pair in new [] { new [] {I18n.Tr("Server wecken"), "wake"}, new [] {I18n.Tr("Server benötigt"), "need"}, new [] {I18n.Tr("Server freigeben"), "release"} }) {
                string action = pair[1]; menu.Items.Add(pair[0], null, async (s,e) => await RunAction(action));
            }
            menu.Items.Add(I18n.Tr("Agent und Statussymbol beenden"), null, (s,e) => Exit());
            tray.Icon = icons.Offline; tray.Text = "Heimserver Manager Client"; tray.ContextMenuStrip = menu; tray.Visible = true;
            tray.DoubleClick += (s,e) => OpenWindow();
            timer.Interval = 1000; timer.Tick += async (s,e) => await Tick(); timer.Start();
            if (!test) SystemEvents.PowerModeChanged += PowerChanged;
        }
        protected override void SetVisibleCore(bool value) {
            if (hiddenStart) { value = false; hiddenStart = false; }
            base.SetVisibleCore(value);
        }
        void Field(TableLayoutPanel grid, string key, string label, bool secret = false) {
            AddField(grid, key, label, new TextBox { UseSystemPasswordChar = secret, MaxLength = 2048 });
        }
        void Combo(TableLayoutPanel grid, string key, string label, Choice[] choices) {
            var combo = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList }; combo.Items.AddRange(choices); AddField(grid, key, label, combo);
        }
        void AddField(TableLayoutPanel grid, string key, string label, Control control) {
            int row = grid.RowCount++; fields[key] = control; control.Dock = DockStyle.Top; control.Margin = new Padding(3, 4, 3, 8);
            grid.Controls.Add(new Label { Text = label, AutoSize = true, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft }, 0, row); grid.Controls.Add(control, 1, row);
        }
        void Fill(Config c) {
            foreach (var pair in fields) {
                var value = (string)typeof(Config).GetField(pair.Key).GetValue(c) ?? "";
                var combo = pair.Value as ComboBox;
                if (combo == null) pair.Value.Text = value;
                else combo.SelectedItem = combo.Items.Cast<Choice>().FirstOrDefault(x => x.Key == value);
            }
        }
        Config ReadFields() {
            var c = new Config();
            foreach (var pair in fields) {
                var combo = pair.Value as ComboBox;
                var value = combo == null ? pair.Value.Text : (combo.SelectedItem == null ? "" : ((Choice)combo.SelectedItem).Key);
                typeof(Config).GetField(pair.Key).SetValue(c, value);
            }
            return c.Validate();
        }
        void Button(FlowLayoutPanel panel, string text, Action fn) {
            var b = new Button { Text = text, AutoSize = true, Padding = new Padding(5), Margin = new Padding(3) };
            b.Click += (s,e) => { try { fn(); } catch (ClientError ex) { Error(ex.Message); } catch { Error(I18n.Tr("Aktion fehlgeschlagen. Dateizugriff und Windows-Benutzersitzung prüfen.")); } }; panel.Controls.Add(b);
        }
        void AddAction(FlowLayoutPanel panel, string label, string action) { Button(panel, label, async () => await RunAction(action)); }
        async void ActivateAgent() {
            if(busy||polling){Say(I18n.Tr("Zuerst laufende Aktion abschließen. Kurz warten."));return;}
            try {
                var cfg=ReadFields();
                if(cfg.TOKEN.StartsWith("setup:")) {busy=true;Say(I18n.Tr("Persönliches Profil über HTTPS aktivieren …"));cfg=await Task.Run(()=>DeviceBinding.Enroll(cfg));busy=false;Fill(cfg);}
                if(Save(true)){startupPending=true;lastBeat=DateTime.MinValue;Say(I18n.Tr("Agent aktiviert. Eigene Benutzer-Geräte-Zuordnung übernommen."));}
            }catch(Exception ex){Say(I18n.Tr("Einrichtung fehlgeschlagen. HTTPS prüfen, bei abgelaufenem Code neues Profil herunterladen. ")+ex.Message);}finally{busy=false;}
        }
        void PairDevice() {
            if(busy||polling){Say(I18n.Tr("Zuerst laufende Aktion abschließen. Kurz warten."));return;}
            busy=true;
            try { DeviceBinding.Dialog(this,ReadFields(),next=>{busy=false;Fill(next);if(!Save(null))throw new ClientError(I18n.Tr("Kopplung lokal nicht gespeichert. Erneut koppeln."));Say(I18n.Tr("Eigene Benutzer-Geräte-Kopplung gespeichert."));}); }
            catch(Exception ex){Say(ex.Message);}finally{busy=false;}
        }
        bool Save(bool? enabled) {
            if (busy || polling) { Say(I18n.Tr("Eine Aktion läuft. Kurz warten oder die Aktion abbrechen.")); return false; }
            try {
                var next = new Saved { config = ReadFields(), enabled = enabled ?? saved.enabled };
                if (autostart.Checked) WindowsIntegration.Install();
                Storage.Save(next); saved = next;
                WindowsIntegration.SetAutostart(autostart.Checked);
                generation++; lastBeat = DateTime.MinValue; lastPoll = DateTime.MinValue;
                Say(I18n.Tr("Gespeichert. Automatisches Wecken nach Anmeldung nur im Modus ‚Mit Server starten‘ und bei aktiviertem Agenten."));
                return true;
            } catch (ClientError ex) { Error(ex.Message); return false; }
            catch { Error(I18n.Tr("Einstellungen konnten nicht vollständig gespeichert werden. Windows-Datei- und Autostartberechtigungen prüfen.")); return false; }
        }
        void Import() {
            using (var picker = new OpenFileDialog { Filter = I18n.Tr("Client-Profil (*.json)|*.json"), Title = I18n.Tr("Client-Profil aus dem Manager") })
                if (picker.ShowDialog(this) == DialogResult.OK) { Fill(Json.Import(picker.FileName)); var profile=Json.Read<Profile>(File.ReadAllBytes(picker.FileName)); if(profile.https!=null)Extras.SaveHttps(profile.https);else if(File.Exists(Extras.HttpsPath))File.Delete(Extras.HttpsPath); Say(I18n.Tr("Profil geladen; noch nicht gespeichert. Token-Datei geschützt aufbewahren.")); }
        }
        void Install() {
            WindowsIntegration.Install();
            if (File.Exists(Storage.ConfigPath)) WindowsIntegration.SetAutostart(autostart.Checked);
            Say(I18n.Tr("Für diesen Benutzer installiert. Startmenü: Heimserver Manager Client. Vorhandene Einstellungen bleiben erhalten."));
        }
        void DeactivateAgent() {
            if (busy || polling) { if (actionCancel != null) actionCancel.Cancel(); Say(I18n.Tr("Laufende Aktion wird beendet. Anschließend erneut deaktivieren.")); return; }
            if (File.Exists(Storage.ConfigPath)) {
                var next = new Saved { config = saved.config, enabled = false }; Storage.Save(next); saved = next;
            }
            WindowsIntegration.SetAutostart(false); autostart.Checked = false; generation++; startupPending = false;
            Say(I18n.Tr("Agent und Autostart deaktiviert. Letzter Serverbedarf verfällt gemäß Ablaufzeit im Manager; bei Bedarf vorher ‚Server freigeben‘ wählen."));
        }
        void Remove() {
            if (MessageBox.Show(this, I18n.Tr("Agent deaktivieren und Autostart / Startmenüeintrag entfernen? Konfiguration bleibt erhalten. Die Programmdateien können nach Beenden aus dem angezeigten Ordner gelöscht werden."), I18n.Tr("Integration entfernen"), MessageBoxButtons.OKCancel) != DialogResult.OK) return;
            if (busy || polling) { Say(I18n.Tr("Bitte laufende Aktion zuerst beenden.")); return; }
            DeactivateAgent(); WindowsIntegration.RemoveIntegration(); Say(I18n.Tr("Integration entfernt. Nach Beenden bei Bedarf Ordner löschen: ") + Path.GetDirectoryName(WindowsIntegration.InstallDirectory));
        }
        async Task RunAction(string action) {
            if (busy || testMode) return;
            Config c;
            try { c = saved.config.Validate(); } catch (ClientError ex) { Error(ex.Message + I18n.Tr(" Zuerst Einstellungen speichern.")); return; }
            connecting = true; SetTray(); busy = true; actionCancel = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
            Say(I18n.Tr("Aktion läuft … Warten auf den Server kann bis zu zehn Minuten dauern."));
            try { await Protocol.Action(c, action, actionCancel.Token); Say(I18n.Tr("Aktion abgeschlossen.")); }
            catch (OperationCanceledException) { Say(I18n.Tr("Aktion abgebrochen.")); }
            catch (ClientError ex) { Say(ex.Message); }
            catch { Say(I18n.Tr("Aktion fehlgeschlagen. Netzwerk und Einstellungen prüfen.")); }
            finally { connecting = false; connected = false; SetTray(); busy = false; actionCancel.Dispose(); actionCancel = null; lastPoll = DateTime.MinValue; }
        }
        async void BeginStartup() { await RunAction("connect"); }
        async Task Tick() {
            if (openEvent != null && openEvent.WaitOne(0)) OpenWindow();
            if (testMode || quitting) return;
            if (startupPending) {
                startupPending = false;
                if (saved.enabled && saved.config.CLIENT_MODE == "with_server") { BeginStartup(); }
            }
            if (polling || DateTime.UtcNow - lastPoll < TimeSpan.FromSeconds(15)) return;
            Config c;
            try { c = saved.config.Validate(); } catch { status.Text = I18n.Tr("Noch nicht eingerichtet · Agent inaktiv"); return; }
            polling = true; lastPoll = DateTime.UtcNow; int current = generation;
            bool online = false, authenticated = false; string beat = saved.enabled ? I18n.Tr("aktiv") : I18n.Tr("inaktiv");
            try {
                try { await Protocol.Health(c, lifetime.Token); online = true; } catch (ClientError) { }
                if (online && !c.TOKEN.StartsWith("setup:")) { try { await Protocol.Status(c, lifetime.Token); authenticated = true; } catch (ClientError) { } }
                if (saved.enabled && DateTime.UtcNow - lastBeat >= TimeSpan.FromSeconds(60)) {
                    lastBeat = DateTime.UtcNow;
                    try { await Protocol.Heartbeat(c, lifetime.Token); beat = I18n.Tr("bestätigt ") + DateTime.Now.ToString("HH:mm:ss"); }
                    catch (ClientError ex) { beat = I18n.Tr("Fehler"); Storage.Log(I18n.Tr("Heartbeat fehlgeschlagen.")); if (!busy) notice.Text = ex.Message; }
                }
                if (!quitting && current == generation) {
                    status.Text = (online ? I18n.Tr("Server erreichbar") : I18n.Tr("Server nicht erreichbar")) + " · Heartbeat: " + beat + I18n.Tr("\nErreichbarkeit allein bestätigt keine gültige Agenten-Anmeldung.");
                    connected = authenticated; SetTray();
                }
            } catch (OperationCanceledException) { }
            catch { if (!quitting) { status.Text = I18n.Tr("Statusprüfung fehlgeschlagen"); connected = false; SetTray(); } }
            finally { polling = false; }
        }
        void SetTray() {
            tray.Icon = connecting ? icons.Connecting : (connected ? icons.Online : icons.Offline);
            tray.Text = connecting ? I18n.Tr("Verbindung wird hergestellt …") : (connected ? I18n.Tr("Verbunden · Anmeldung bestätigt") : I18n.Tr("Keine bestätigte Agenten-Verbindung"));
        }
        void PowerChanged(object sender, PowerModeChangedEventArgs e) {
            if (e.Mode == PowerModes.Resume && !IsDisposed && IsHandleCreated) BeginInvoke((Action)(() => { lastPoll = DateTime.MinValue; lastBeat = DateTime.MinValue; }));
        }
        void Say(string text) { if (!IsDisposed && !quitting) notice.Text = text; if (!testMode) Storage.Log(SafeLog(text)); }
        string SafeLog(string text) {
            // Only fixed action state goes into logs; never persist editable values or directory paths.
            if (text == I18n.Tr("Aktion abgeschlossen.") || text == I18n.Tr("Aktion abgebrochen.")) return text;
            return I18n.Tr("Client-Status geändert; Details im Fenster.");
        }
        void Error(string text) { if (!quitting) { OpenWindow(); MessageBox.Show(this, text, "Heimserver Manager Client", MessageBoxButtons.OK, MessageBoxIcon.Warning); } }
        void Logs() {
            var path = Path.Combine(Storage.Root, "client.log");
            using (var form = new Form { Text = I18n.Tr("Client-Protokoll"), Size = new Size(750, 450), StartPosition = FormStartPosition.CenterParent }) {
                form.Controls.Add(new TextBox { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Both, Text = File.Exists(path) ? File.ReadAllText(path) : I18n.Tr("Noch kein Protokoll vorhanden.") }); form.ShowDialog(this);
            }
        }
        public void OpenWindow() { hiddenStart = false; Show(); WindowState = FormWindowState.Normal; Activate(); }
        public void Exit() { quitting = true; Close(); }
        protected override void OnFormClosing(FormClosingEventArgs e) {
            if (!quitting && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); return; }
            quitting = true; timer.Stop(); lifetime.Cancel(); tray.Visible = false; base.OnFormClosing(e);
        }
        protected override void Dispose(bool disposing) {
            if (disposing) { if (!testMode) SystemEvents.PowerModeChanged -= PowerChanged; timer.Dispose(); tray.Dispose(); icons.Dispose(); lifetime.Cancel(); }
            base.Dispose(disposing);
        }
    }
}
