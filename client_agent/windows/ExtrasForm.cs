// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.IO;
using System.Drawing;
using System.Diagnostics;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
namespace HeimserverClient {
 public sealed class ExtrasForm:Form {
  readonly Config config;readonly Label status=new Label{AutoSize=true,MaximumSize=new Size(620,0)};
  readonly FlowLayoutPanel panel=new FlowLayoutPanel{Dock=DockStyle.Fill,AutoScroll=true,FlowDirection=FlowDirection.TopDown,WrapContents=false,Padding=new Padding(12)};
  bool busy;
  public ExtrasForm(Config c,bool https,Action<string> setUrl){
   config=c.Validate();Text=https?I18n.Tr("Privates HTTPS"):I18n.Tr("Eigene Client-Sicherungen");Size=new Size(690,530);Controls.Add(panel);
   FormClosing+=(s,e)=>{if(busy){e.Cancel=true;MessageBox.Show(this,I18n.Tr("Aktion läuft noch. Bitte warten."));}};
   if(https)BuildHttps(setUrl);else BuildBackup();panel.Controls.Add(status);
  }
  void Note(string text){panel.Controls.Add(new Label{Text=text,AutoSize=true,MaximumSize=new Size(620,0),Margin=new Padding(3,6,3,10)});}
  void Button(string title,Action action){var b=new Button{Text=title,AutoSize=true};b.Click+=(s,e)=>{if(!busy)action();};panel.Controls.Add(b);}
  bool Confirm(string text){return MessageBox.Show(this,text,Text,MessageBoxButtons.OKCancel,MessageBoxIcon.Question)==DialogResult.OK;}
  string Folder(string title){using(var d=new FolderBrowserDialog{Description=title})return d.ShowDialog(this)==DialogResult.OK?d.SelectedPath:null;}
  void Progress(string text){if(!IsDisposed&&IsHandleCreated)BeginInvoke((Action)(()=>status.Text=text));}
  async void Work(Func<string> run){if(busy)return;busy=true;status.Text=I18n.Tr("Aktion läuft …");try{status.Text=await Task.Run(run);}catch(Exception e){status.Text=e.Message;MessageBox.Show(this,e.Message,Text,MessageBoxButtons.OK,MessageBoxIcon.Error);}finally{busy=false;}}
  void BuildBackup(){
   Note(I18n.Tr("Dateibackup ausgewählter Benutzerordner. Kein Systemabbild: Windows, Registry, Berechtigungen, Links und Spezialdateien werden nicht vollständig gesichert. Programme vorher schließen. Rücksicherung nur in einen neuen Ordner. Jeder Benutzer benötigt ein eigenes Client-Profil."));
   var list=new ComboBox{Width=620,DropDownStyle=ComboBoxStyle.DropDownList};panel.Controls.Add(list);
   Button(I18n.Tr("Sicherungsstände laden"),()=>Work(()=>{var r=Extras.Call(config,"list");Invoke((Action)(()=>{list.Items.Clear();foreach(var item in r.backups??new BackupItem[0])list.Items.Add(item);if(list.Items.Count>0)list.SelectedIndex=0;}));return I18n.Tr("Eigene Sicherungsstände geladen.");}));
   Button(I18n.Tr("Ordner sichern"),()=>{string src=Folder(I18n.Tr("Zu sichernden Benutzerordner auswählen"));if(src!=null&&Confirm(I18n.Tr("Diesen Ordner auf dem Manager sichern? HTTP ist unverschlüsselt; für vertrauliche Dateien zuerst HTTPS einrichten.")))Work(()=>Extras.Backup(config,src,Progress));});
   Button(I18n.Tr("Ausgewählten Stand wiederherstellen"),()=>{var item=list.SelectedItem as BackupItem;if(item==null){MessageBox.Show(this,I18n.Tr("Zuerst einen Sicherungsstand auswählen."));return;}string parent=Folder(I18n.Tr("Übergeordneten Zielordner wählen"));if(parent!=null){string target=Path.Combine(parent,"Wiederherstellung-"+item.id.Substring(0,12));if(Confirm(I18n.Tr("In neuen Ordner wiederherstellen: ")+target+I18n.Tr("? Bei Fehler bleibt eventuell ein Teilstand dort erhalten.")))Work(()=>Extras.Restore(config,item,target,Progress));}});
   Button(I18n.Tr("Unvollständige Übertragung verwerfen"),()=>{if(Confirm(I18n.Tr("Nur die unvollständige Übertragung dieses Clients verwerfen?")))Work(()=>{Extras.Call(config,"cancel",Encoding.UTF8.GetBytes("{}"));return I18n.Tr("Unvollständige Übertragung verworfen.");});});
  }
  void BuildHttps(Action<string> setUrl){
   var p=Extras.LoadHttps();if(p==null){Note(I18n.Tr("Zuerst privates HTTPS im Manager einrichten. Anschließend neues JSON-Client-Profil importieren; dieses enthält das öffentliche Stammzertifikat."));return;}
   Note(I18n.Tr("Hostname: ")+p.hostname+"\nSHA-256: "+p.sha256+I18n.Tr("\nFingerabdruck mit Einstellungen → HTTPS-Zugang im Manager vergleichen. Der Import erteilt diesem Stammzertifikat Vertrauen."));
   Note(I18n.Tr("Optional feste Server-IP für den Namenseintrag. Leer lassen, wenn der Router den Namen bereits auflöst."));
   var ip=new TextBox{Text=p.ip??"",Width=400};panel.Controls.Add(ip);
   Button(I18n.Tr("Einrichten (Windows-Administratorfreigabe)"),()=>{p.ip=ip.Text.Trim();if(Confirm(I18n.Tr("Fingerabdruck geprüft? Stammzertifikat vertrauen und optionalen Namenseintrag einrichten?")))Work(()=>{Extras.ElevateHttps(p,false);return I18n.Tr("Eingerichtet. Verbindung jetzt prüfen.");});});
   Button(I18n.Tr("HTTPS prüfen und übernehmen"),()=>Work(()=>{string url=Extras.TestHttps(p);Invoke((Action)(()=>{if(Confirm(I18n.Tr("HTTPS erfolgreich geprüft. Manager-Adresse auf ")+url+I18n.Tr(" umstellen?")))setUrl(url);}));return I18n.Tr("HTTPS mit gültigem Zertifikat erreichbar.");}));
   Button(I18n.Tr("Eigene Einrichtung entfernen"),()=>{if(Confirm(I18n.Tr("Nur das von diesem Assistenten hinzugefügte Stammzertifikat und seinen Namenseintrag entfernen?")))Work(()=>{Extras.ElevateHttps(p,true);return I18n.Tr("Eigene Einrichtung entfernt.");});});
  }
 }
}
