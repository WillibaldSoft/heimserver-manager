// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Collections.Generic;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Diagnostics;
using Microsoft.Win32;
namespace HeimserverClient {
 [DataContract] public class HttpsProfile {
  [DataMember] public string hostname;
  [DataMember] public int port;
  [DataMember] public string ip;
  [DataMember] public string ca_pem;
  [DataMember] public string sha256;
 }
 [DataContract] public class BackupItem {
  [DataMember] public string id;
  [DataMember] public string created;
  [DataMember] public string name;
  [DataMember] public string sha256;
  [DataMember] public long bytes;
  public override string ToString(){return created+" · "+name+" · "+(bytes/1024/1024)+" MiB";}
 }
 [DataContract] public class BackupReply {
  [DataMember] public BackupItem[] backups;
  [DataMember] public string id;
  [DataMember] public string error;
 }
 [DataContract] public class BackupBegin {
  [DataMember] public long bytes;
  [DataMember] public string sha256;
  [DataMember] public string name;
 }
 public static class Extras {
  public const int Chunk=4*1024*1024;
  public static string HttpsPath {get{return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"HeimserverManagerClient","https.json");}}
  public static string Hash(Stream stream){using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(stream)).Replace("-","").ToLowerInvariant();}
  public static string HashFile(string file){using(var f=File.OpenRead(file))return Hash(f);}
  public static HttpWebResponse Request(Config config,string action,byte[] data=null,string query="",bool json=true){
   var c=config.Validate();var r=(HttpWebRequest)WebRequest.Create(c.SERVER_URL+"/api/clients/backup?action="+action+query);
   r.AllowAutoRedirect=false;r.Timeout=300000;r.ReadWriteTimeout=300000;r.Headers["Authorization"]="Bearer "+c.TOKEN;DeviceBinding.Headers(r);
   if(data!=null){r.Method="POST";r.ContentType=json?"application/json":"application/octet-stream";r.ContentLength=data.Length;using(var s=r.GetRequestStream())s.Write(data,0,data.Length);}
   try {var response=(HttpWebResponse)r.GetResponse();if((int)response.StatusCode>=300){response.Dispose();throw new ClientError(I18n.Tr("Anfrage umgeleitet oder abgelehnt."));}return response;}
   catch(WebException e){using(var response=e.Response){if(response!=null){try{using(var s=response.GetResponseStream())using(var m=new MemoryStream()){var b=new byte[4096];int n=s.Read(b,0,b.Length);m.Write(b,0,n);var reply=Json.Read<BackupReply>(m.ToArray());throw new ClientError(reply.error??I18n.Tr("Sicherung abgelehnt."));}}catch(ClientError){throw;}catch{}}}throw new ClientError(I18n.Tr("Server-Anfrage fehlgeschlagen. HTTPS, Verbindung und Client-Profil prüfen."));}
  }
  public static BackupReply Call(Config c,string action,byte[] data=null,string query="",bool json=true){using(var r=Request(c,action,data,query,json))using(var s=r.GetResponseStream())using(var m=new MemoryStream()){s.CopyTo(m);if(m.Length>1024*1024)throw new ClientError(I18n.Tr("Antwort zu groß."));m.Position=0;return (BackupReply)new DataContractJsonSerializer(typeof(BackupReply)).ReadObject(m);}}
  static bool Reparse(string path){return (File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0;}
  static IEnumerable<string> Files(string path){yield return path;foreach(var f in Directory.GetFiles(path))if(!Reparse(f))yield return f;foreach(var d in Directory.GetDirectories(path))if(!Reparse(d))foreach(var f in Files(d))yield return f;}
  public static string Backup(Config c,string source,Action<string> progress){
   source=Path.GetFullPath(source).TrimEnd(Path.DirectorySeparatorChar);
   if(!Directory.Exists(source)||source.Length<4||Reparse(source))throw new ClientError(I18n.Tr("Vorhandenen Benutzerordner auswählen, kein Laufwerk oder Link."));
   string tmp=Path.Combine(Path.GetTempPath(),"hsm-backup-"+Guid.NewGuid().ToString("N")+".zip");
   if(tmp.StartsWith(source+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new ClientError(I18n.Tr("Temporäre Ablage liegt in der Quelle. Engeren Ordner wählen."));
   try{
    int count=0;
    using(var stream=new FileStream(tmp,FileMode.CreateNew,FileAccess.ReadWrite))using(var z=new ZipArchive(stream,ZipArchiveMode.Create)){
     foreach(var file in Files(source)){
      if(Directory.Exists(file)){if(file!=source)z.CreateEntry("files/"+file.Substring(source.Length+1).Replace('\\','/')+"/");continue;}
      var before=new FileInfo(file);long size=before.Length;DateTime time=before.LastWriteTimeUtc;
      using(var input=new FileStream(file,FileMode.Open,FileAccess.Read,FileShare.Read)){
       if(Reparse(file))throw new ClientError(I18n.Tr("Datei wurde durch einen Link ersetzt."));
       var entry=z.CreateEntry("files/"+file.Substring(source.Length+1).Replace('\\','/'),CompressionLevel.Optimal);
       if(time.Year>=1980&&time.Year<=2107)entry.LastWriteTime=new DateTimeOffset(time);
       using(var output=entry.Open())input.CopyTo(output);
      }
      var after=new FileInfo(file);if(after.Length!=size||after.LastWriteTimeUtc!=time)throw new ClientError(I18n.Tr("Datei wurde während der Sicherung verändert; erneut sichern."));
      count++;progress(I18n.Tr("Dateien sammeln: ")+count);
     }
     using(var w=new StreamWriter(z.CreateEntry("hsm-backup.json").Open()))w.Write("{\"format\":\"client-zip-v1\",\"scope\":\"user-files\"}");
    }
    progress(I18n.Tr("Prüfsumme berechnen …"));long total=new FileInfo(tmp).Length;
    var reply=Call(c,"begin",Json.Write(new BackupBegin{bytes=total,sha256=HashFile(tmp),name=Path.GetFileName(source)}));
    if(!Regex.IsMatch(reply.id??"","^[a-f0-9]{32}$"))throw new ClientError(I18n.Tr("Ungültige Sicherungskennung."));
    using(var input=File.OpenRead(tmp)){long offset=0;var block=new byte[Chunk];int read;
     while((read=input.Read(block,0,block.Length))>0){var bytes=block.Take(read).ToArray();Call(c,"part",bytes,"&id="+reply.id+"&offset="+offset,false);offset+=read;progress(I18n.Tr("Übertragen: ")+(offset*100/total)+" %");}
    }
    progress(I18n.Tr("Server prüft das Archiv …"));Call(c,"finish",Encoding.UTF8.GetBytes("{}"),"&id="+reply.id);
    return I18n.Tr("Sicherung abgeschlossen: ")+count+I18n.Tr(" Dateien. Verknüpfungen und Spezialdateien sind nicht enthalten.");
   }finally{if(File.Exists(tmp))File.Delete(tmp);}
  }
  public static string Restore(Config c,BackupItem item,string target,Action<string> progress){
   if(!Regex.IsMatch(item.id??"","^[a-f0-9]{32}$"))throw new ClientError(I18n.Tr("Ungültige Sicherungskennung."));
   target=Path.GetFullPath(target);if(Directory.Exists(target)||File.Exists(target))throw new ClientError(I18n.Tr("Ziel muss ein neuer Ordner sein."));
   for(var p=new DirectoryInfo(Path.GetDirectoryName(target));p!=null;p=p.Parent)if(Reparse(p.FullName))throw new ClientError(I18n.Tr("Keine Links im Wiederherstellungsziel verwenden."));
   string tmp=Path.Combine(Path.GetTempPath(),"hsm-restore-"+Guid.NewGuid().ToString("N")+".zip");
   try{
    using(var r=Request(c,"download",null,"&id="+item.id))using(var s=r.GetResponseStream())using(var f=new FileStream(tmp,FileMode.CreateNew)){var buffer=new byte[Chunk];long size=0;int n;while((n=s.Read(buffer,0,buffer.Length))>0){f.Write(buffer,0,n);size+=n;progress(I18n.Tr("Heruntergeladen: ")+(size/1024/1024)+" MiB");}}
    if(HashFile(tmp)!=item.sha256)throw new ClientError(I18n.Tr("Prüfsumme stimmt nicht. Keine Wiederherstellung."));
    using(var f=File.OpenRead(tmp))using(var z=new ZipArchive(f,ZipArchiveMode.Read)){
     var names=new HashSet<string>(StringComparer.OrdinalIgnoreCase);long size=0;
     foreach(var entry in z.Entries){if(entry.FullName=="hsm-backup.json")continue;
      string n=entry.FullName.TrimEnd('/');var parts=n.Split('/');
      if(!n.StartsWith("files/")||n.Contains("\\")||n.Contains(":")||parts.Any(p=>p==""||p=="."||p==".."||p.EndsWith(".")||p.EndsWith(" ")||p.IndexOfAny(Path.GetInvalidFileNameChars())>=0||Regex.IsMatch(p,@"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)",RegexOptions.IgnoreCase))||((entry.ExternalAttributes>>16)&0xF000)==0xA000||!names.Add(n))throw new ClientError(I18n.Tr("Unsicherer oder unter Windows nicht darstellbarer Archiveintrag."));
      size+=entry.Length;
     }
     if(new DriveInfo(Path.GetPathRoot(target)).AvailableFreeSpace<size+128*1024*1024)throw new ClientError(I18n.Tr("Zu wenig freier Speicher."));
     Directory.CreateDirectory(target);int count=0;
     foreach(var entry in z.Entries){if(entry.FullName=="hsm-backup.json")continue;string dest=Path.Combine(target,entry.FullName.Substring(6).Replace('/',Path.DirectorySeparatorChar));if(entry.FullName.EndsWith("/")){Directory.CreateDirectory(dest);continue;}Directory.CreateDirectory(Path.GetDirectoryName(dest));using(var input=entry.Open())using(var output=new FileStream(dest,FileMode.CreateNew))input.CopyTo(output);File.SetLastWriteTimeUtc(dest,entry.LastWriteTime.UtcDateTime);progress(I18n.Tr("Dateien wiederherstellen: ")+(++count));}
    }
    return I18n.Tr("Wiederhergestellt: ")+target;
   }finally{if(File.Exists(tmp))File.Delete(tmp);}
  }
  public static HttpsProfile LoadHttps(){return File.Exists(HttpsPath)?Json.Read<HttpsProfile>(File.ReadAllBytes(HttpsPath)):null;}
  public static void SaveHttps(HttpsProfile profile){ValidateHttps(profile);Directory.CreateDirectory(Path.GetDirectoryName(HttpsPath));File.WriteAllBytes(HttpsPath,Json.Write(profile));}
  public static X509Certificate2 ValidateHttps(HttpsProfile p){
   if(p==null||!Regex.IsMatch(p.hostname??"",@"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")||p.hostname.Length>253||p.hostname.Contains("..")||p.port<1||p.port>65535||!Regex.IsMatch(p.sha256??"","^[a-fA-F0-9]{64}$")||(p.ca_pem??"").Length>32768)throw new ClientError(I18n.Tr("Ungültiges HTTPS-Profil."));
   IPAddress address;if(IPAddress.TryParse(p.hostname,out address))throw new ClientError(I18n.Tr("Hostname statt IP-Adresse erforderlich."));
   if(!String.IsNullOrWhiteSpace(p.ip)&&!IPAddress.TryParse(p.ip,out address))throw new ClientError(I18n.Tr("Ungültige Server-IP."));
   string pem=p.ca_pem.Replace("-----BEGIN CERTIFICATE-----","").Replace("-----END CERTIFICATE-----","");var cert=new X509Certificate2(Convert.FromBase64String(pem));
   using(var s=new MemoryStream(cert.RawData))if(Hash(s)!=p.sha256.ToLowerInvariant())throw new ClientError(I18n.Tr("Zertifikat-Fingerabdruck stimmt nicht."));
   var basic=cert.Extensions.OfType<X509BasicConstraintsExtension>().FirstOrDefault();
   if(basic==null||!basic.CertificateAuthority||cert.Subject!=cert.Issuer||cert.NotAfter<DateTime.Now||cert.NotBefore>DateTime.Now||cert.HasPrivateKey)throw new ClientError(I18n.Tr("Kein gültiges öffentliches Stammzertifikat."));
   return cert;
  }
  public static void ElevateHttps(HttpsProfile p,bool remove){
   ValidateHttps(p);string tmp=Path.Combine(Path.GetTempPath(),"hsm-trust-"+Guid.NewGuid().ToString("N")+".json");File.WriteAllBytes(tmp,Json.Write(p));
   try{var start=new ProcessStartInfo(System.Windows.Forms.Application.ExecutablePath,"--https-"+(remove?"remove":"install")+" \""+tmp+"\""){UseShellExecute=true,Verb="runas"};using(var process=Process.Start(start)){process.WaitForExit();if(process.ExitCode!=0)throw new ClientError(I18n.Tr("Zertifikatseinrichtung nicht abgeschlossen."));}SaveHttps(p);}finally{File.Delete(tmp);}
  }
  public static void ApplyHttps(string path,bool remove){
   if(new FileInfo(path).Length>65536)throw new ClientError(I18n.Tr("Profil zu groß."));var p=Json.Read<HttpsProfile>(File.ReadAllBytes(path));var cert=ValidateHttps(p);
   string hosts=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),@"drivers\etc\hosts");string old=File.ReadAllText(hosts);
   string marker="# Heimserver-Manager "+p.sha256.ToLowerInvariant()+" "+p.hostname;
   var lines=old.Split(new[]{"\r\n","\n"},StringSplitOptions.None).Where(l=>!l.EndsWith(marker)).ToList();
   if(!remove&&!String.IsNullOrWhiteSpace(p.ip)){
    foreach(var line in lines){var words=line.Split('#')[0].Split((char[])null,StringSplitOptions.RemoveEmptyEntries);if(words.Skip(1).Any(w=>String.Equals(w,p.hostname,StringComparison.OrdinalIgnoreCase)))throw new ClientError(I18n.Tr("Hostname bereits in hosts vorhanden. Vorhandenen Eintrag zuerst prüfen."));}
    lines.Add(p.ip+" "+p.hostname+" "+marker);
   }
   using(var key=Registry.LocalMachine.CreateSubKey(@"SOFTWARE\HeimserverManagerClient\Certificates"))using(var store=new X509Store(StoreName.Root,StoreLocation.LocalMachine)){
    store.Open(OpenFlags.ReadWrite);var existing=store.Certificates.Find(X509FindType.FindByThumbprint,cert.Thumbprint,false);
    if(remove){if((string)key.GetValue(p.sha256)=="added"){foreach(var x in existing)store.Remove(x);key.DeleteValue(p.sha256,false);}}
    else if(existing.Count==0){store.Add(cert);key.SetValue(p.sha256,"added");}
   }
   string updated=String.Join(Environment.NewLine,lines);
   if(updated!=old){File.WriteAllText(hosts+".heimserver-manager.before",old);File.WriteAllText(hosts,updated);}
  }
  public static string TestHttps(HttpsProfile p){ValidateHttps(p);string url="https://"+p.hostname+":"+p.port;var r=(HttpWebRequest)WebRequest.Create(url+"/api/health");r.AllowAutoRedirect=false;r.Timeout=10000;using(var result=(HttpWebResponse)r.GetResponse()){if(result.StatusCode!=HttpStatusCode.OK)throw new ClientError(I18n.Tr("HTTPS-Prüfung fehlgeschlagen."));}return url;}
 }
}
