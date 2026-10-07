// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Runtime.Serialization;
using System.Windows.Forms;
using System.Threading.Tasks;
using Microsoft.Win32;
namespace HeimserverClient {
 [DataContract] public class PairData {
  [DataMember] public string code;
  [DataMember] public string device_id;
  [DataMember] public string local_user;
  [DataMember] public string hostname;
  [DataMember] public string mac;
  [DataMember] public string mode;
 }
 [DataContract] public class PairReply {
  [DataMember] public string token;
  [DataMember] public string name;
  [DataMember] public string server_mac;
 }
 [DataContract] public class AccessReply { [DataMember] public string csrf; }
 public static class DeviceBinding {
  static string Hash(string s){using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(Encoding.UTF8.GetBytes(s))).Replace("-","").ToLowerInvariant();}
  public static string Device(){
   using(var root=RegistryKey.OpenBaseKey(RegistryHive.LocalMachine,RegistryView.Registry64))
   using(var key=root.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography")){
    string id=key==null?null:Convert.ToString(key.GetValue("MachineGuid"));
    if(String.IsNullOrWhiteSpace(id))throw new ClientError(I18n.Tr("Stabile Windows-Gerätekennung fehlt."));return Hash("hsm-device:"+id);
   }
  }
  public static string User(){using(var id=WindowsIdentity.GetCurrent()){if(id.User==null)throw new ClientError(I18n.Tr("Windows-Benutzerkennung fehlt."));return Hash("hsm-user:"+id.User.Value);}}
  public static void Headers(HttpWebRequest r){r.Headers["X-HSM-Device"]=Device();r.Headers["X-HSM-User"]=User();}
  static byte[] Request(string url,CookieContainer cookies,byte[] data=null,string type="application/json",string csrf=null,bool login=false){
   var r=(HttpWebRequest)WebRequest.Create(url);r.AllowAutoRedirect=false;r.CookieContainer=cookies;r.Timeout=30000;r.ReadWriteTimeout=30000;
   if(csrf!=null)r.Headers["X-Server-Manager-CSRF"]=csrf;
   if(data!=null){r.Method="POST";r.ContentType=type;r.ContentLength=data.Length;using(var s=r.GetRequestStream())s.Write(data,0,data.Length);}
   try {using(var response=(HttpWebResponse)r.GetResponse()){
    if(login){if((int)response.StatusCode!=303)throw new ClientError(I18n.Tr("Anmeldung nicht bestätigt."));return new byte[0];}
    if((int)response.StatusCode!=200)throw new ClientError(I18n.Tr("Manager-Anfrage abgelehnt."));
    using(var s=response.GetResponseStream())using(var m=new MemoryStream()){s.CopyTo(m);if(m.Length>1024*1024)throw new ClientError(I18n.Tr("Antwort zu groß."));return m.ToArray();}
   }}catch(WebException e){using(var response=e.Response){throw new ClientError(I18n.Tr("Anmeldung/Kopplung abgelehnt. HTTPS, Benutzerfreigabe und Passwort prüfen."));}}
  }
  static string Attr(string tag,string key){var m=Regex.Match(tag,"\\b"+key+"\\s*=\\s*['\"]([^'\"]*)['\"]",RegexOptions.IgnoreCase);return WebUtility.HtmlDecode(m.Groups[1].Value);}
  public static Config Enroll(Config c){
   c.Validate();if(!c.TOKEN.StartsWith("setup:"))return c;
   if(!c.SERVER_URL.StartsWith("https://",StringComparison.OrdinalIgnoreCase))throw new ClientError(I18n.Tr("Zuerst geprüftes HTTPS einrichten."));
   var data=new PairData{code=c.TOKEN.Substring(6),device_id=Device(),local_user=User(),hostname=Environment.MachineName,mac=c.CLIENT_MAC,mode=c.CLIENT_MODE};
   var result=Json.Read<PairReply>(Request(c.SERVER_URL+"/api/clients/enroll",new CookieContainer(),Json.Write(data)));
   if(String.IsNullOrEmpty(result.token)||String.IsNullOrEmpty(result.name))throw new ClientError(I18n.Tr("Einrichtung fehlgeschlagen. Neues Profil herunterladen."));
   var next=c.Copy();next.TOKEN=result.token;next.CLIENT_NAME=result.name;next.SERVER_MAC=result.server_mac??"";return next.Validate();
  }
  public static Config Pair(Config c,string user,string password){
   c.Validate();if(!c.SERVER_URL.StartsWith("https://",StringComparison.OrdinalIgnoreCase))throw new ClientError(I18n.Tr("Kopplung benötigt geprüftes HTTPS."));
   var cookies=new CookieContainer();string html=Encoding.UTF8.GetString(Request(c.SERVER_URL+"/login",cookies));string csrf=null;
   foreach(Match input in Regex.Matches(html,"<input\\b[^>]*>",RegexOptions.IgnoreCase))if(Attr(input.Value,"name")=="auth_csrf")csrf=Attr(input.Value,"value");
   if(String.IsNullOrEmpty(csrf))throw new ClientError(I18n.Tr("Anmeldeformular nicht erkannt."));
   string form="username="+Uri.EscapeDataString(user)+"&password="+Uri.EscapeDataString(password)+"&auth_csrf="+Uri.EscapeDataString(csrf)+"&next=/api/account/access";
   Request(c.SERVER_URL+"/login",cookies,Encoding.UTF8.GetBytes(form),"application/x-www-form-urlencoded",null,true);
   var access=Json.Read<AccessReply>(Request(c.SERVER_URL+"/api/account/access",cookies));
   var result=Json.Read<PairReply>(Request(c.SERVER_URL+"/api/account/agent/pair",cookies,Json.Write(new PairData{device_id=Device(),local_user=User(),hostname=Environment.MachineName,mac=c.CLIENT_MAC,mode=c.CLIENT_MODE}),"application/json",access.csrf));
   if(String.IsNullOrEmpty(result.token)||String.IsNullOrEmpty(result.name))throw new ClientError(I18n.Tr("Kopplungsantwort unvollständig."));
   var next=Json.Read<Config>(Json.Write(c));next.TOKEN=result.token;next.CLIENT_NAME=result.name;next.SERVER_MAC=result.server_mac??"";
   if(next.SERVER_MAC!=""&&next.WAKE_METHOD=="none")next.WAKE_METHOD="wol";return next.Validate();
  }
  public static void Dialog(Form parent,Config config,Action<Config> save){
   using(var d=new Form{Text=I18n.Tr("Benutzer & Gerät koppeln"),Width=500,Height=275,StartPosition=FormStartPosition.CenterParent}){
    var panel=new FlowLayoutPanel{Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown,Padding=new Padding(12),WrapContents=false};d.Controls.Add(panel);
    panel.Controls.Add(new Label{Text=I18n.Tr("Freigegebenes Manager-Konto verwenden. Eigenes Token und eigener Schlafblocker für diesen Benutzer an diesem PC. Passwort wird nicht gespeichert."),Width=450,Height=55});
    var user=new TextBox{Width=440};var password=new TextBox{Width=440,UseSystemPasswordChar=true};panel.Controls.Add(user);panel.Controls.Add(password);
    var button=new Button{Text=I18n.Tr("Anmelden und koppeln"),Width=230};panel.Controls.Add(button);
    button.Click+=async(s,e)=>{button.Enabled=false;string name=user.Text,secret=password.Text;password.Clear();try{var next=await Task.Run(()=>Pair(config,name,secret));save(next);d.Close();}catch(Exception ex){MessageBox.Show(d,ex.Message);button.Enabled=true;}finally{secret=null;}};
    d.ShowDialog(parent);
   }
  }
 }
}
