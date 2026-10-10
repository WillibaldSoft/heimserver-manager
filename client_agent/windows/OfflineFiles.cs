// SPDX-License-Identifier: GPL-3.0-or-later
using System;using System.IO;using System.Linq;using System.Net;using System.Text;using System.Threading;using System.Threading.Tasks;using System.Collections.Generic;using System.Runtime.Serialization;using System.Windows.Forms;using System.Drawing;using System.Runtime.InteropServices;using Microsoft.Win32.SafeHandles;
namespace HeimserverClient {
 [DataContract] public class OfflineFolder { [DataMember] public string id,name,local,exclude;[DataMember] public bool write,delete,wake;[DataMember] public int interval,limit_gib=10;public override string ToString(){return name??id;} }
 [DataContract] public class OfflineFile { [DataMember] public string path,sha;[DataMember] public long size; }
 [DataContract] public class OfflineReply { [DataMember] public OfflineFolder[] folders;[DataMember] public OfflineFile[] files;[DataMember] public string error,sha,parent,current,current_name; }
 public static class OfflineFiles {
  public static string Root=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"HeimserverManagerClient","offline");
  [StructLayout(LayoutKind.Sequential)] struct FileInformation { public uint attributes;public System.Runtime.InteropServices.ComTypes.FILETIME created,accessed,written;public uint volume,high,low,links,indexHigh,indexLow; }
  [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle handle,out FileInformation info);
  static void Regular(string path){if(Environment.OSVersion.Platform!=PlatformID.Win32NT)return;using(var f=File.OpenRead(path)){FileInformation info;if(!GetFileInformationByHandle(f.SafeFileHandle,out info)||info.links!=1)throw new ClientError("Hard links are unsupported");}}
  static int running;static Dictionary<string,DateTime> last=new Dictionary<string,DateTime>();
  public static void Atomic(string path,byte[] bytes){Directory.CreateDirectory(Path.GetDirectoryName(path));string tmp=path+"."+Guid.NewGuid().ToString("N");try{File.WriteAllBytes(tmp,bytes);if(File.Exists(path))File.Replace(tmp,path,null);else File.Move(tmp,path);}finally{if(File.Exists(tmp))File.Delete(tmp);}}
  public static OfflineFolder[] Load(){string p=Path.Combine(Root,"folders.json");return File.Exists(p)?Json.Read<OfflineFolder[]>(File.ReadAllBytes(p)):new OfflineFolder[0];}
  public static void Save(OfflineFolder[] rows){Atomic(Path.Combine(Root,"folders.json"),Json.Write(rows));}
  public static HttpWebResponse Request(Config c,string action,string id="",string path="",string sha="",Stream data=null,string exclude="",string contentSha=""){
   c=c.Validate();if(!c.SERVER_URL.StartsWith("https://",StringComparison.OrdinalIgnoreCase))throw new ClientError(I18n.Tr("Offline-Dateien benötigen HTTPS."));
   var req=(HttpWebRequest)WebRequest.Create(c.SERVER_URL+"/api/clients/offline?action="+action+"&id="+Uri.EscapeDataString(id)+"&path="+Uri.EscapeDataString(path)+"&sha="+Uri.EscapeDataString(sha??"")+"&exclude="+Uri.EscapeDataString(exclude)+"&content_sha="+Uri.EscapeDataString(contentSha));
   req.AllowAutoRedirect=false;req.Timeout=300000;req.ReadWriteTimeout=300000;req.Headers["Authorization"]="Bearer "+c.TOKEN;DeviceBinding.Headers(req);
   if(data!=null){req.Method="POST";req.ContentType="application/octet-stream";req.ContentLength=data.Length;req.AllowWriteStreamBuffering=false;using(var dst=req.GetRequestStream())data.CopyTo(dst);}
   try{var r=(HttpWebResponse)req.GetResponse();if((int)r.StatusCode>=300){r.Dispose();throw new ClientError("Redirect refused");}return r;}
   catch(WebException e){if(e.Response!=null)using(var r=e.Response)using(var s=r.GetResponseStream()){var b=new byte[4096];int n=s.Read(b,0,b.Length);try{throw new ClientError(Json.Read<OfflineReply>(b.Take(n).ToArray()).error??"Request denied");}catch(ClientError){throw;}catch{}}throw new ClientError("Offline request failed; check HTTPS and paired profile");}
  }
  public static OfflineReply Call(Config c,string action,string id="",string path="",string sha="",Stream data=null,string exclude="",string contentSha=""){using(var r=Request(c,action,id,path,sha,data,exclude,contentSha))using(var s=r.GetResponseStream())using(var m=new MemoryStream()){var b=new byte[65536];int n;while((n=s.Read(b,0,b.Length))>0){m.Write(b,0,n);if(m.Length>8*1024*1024)throw new ClientError("Response too large");}return Json.Read<OfflineReply>(m.ToArray());}}
  static void Post(Config c,string action,string id,string path="",string sha=""){using(var s=new MemoryStream())Call(c,action,id,path,sha,s);}
  public static string Local(string root,string path){
   if(String.IsNullOrEmpty(path)||path.Split('/').Any(x=>x==""||x=="."||x==".."||x.StartsWith(".hsm-",StringComparison.OrdinalIgnoreCase)||x.IndexOfAny(Path.GetInvalidFileNameChars())>=0||x.EndsWith(".")||x.EndsWith(" ")))throw new ClientError("Unsafe path");
   string result=Path.GetFullPath(Path.Combine(root,path.Replace('/',Path.DirectorySeparatorChar)));
   if(!result.StartsWith(Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new ClientError("Unsafe path");
   CheckParents(result);return result;
  }
  static void CheckParents(string path){for(string p=path;!String.IsNullOrEmpty(p);p=Path.GetDirectoryName(p)){if((File.Exists(p)||Directory.Exists(p))&&(File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0)throw new ClientError("Links and junctions are unsupported");}}
  public static Dictionary<string,OfflineFile> Scan(string root,string exclude=""){CheckParents(root);if(!Directory.Exists(root))throw new ClientError("Local folder missing");var result=new Dictionary<string,OfflineFile>(StringComparer.Ordinal);Walk(root,root,result,exclude);return result;}
  static void Walk(string root,string dir,Dictionary<string,OfflineFile> rows,string exclude){foreach(string p in Directory.GetFileSystemEntries(dir)){if(Path.GetFileName(p).StartsWith(".hsm-",StringComparison.OrdinalIgnoreCase))continue;string rel=p.Substring(root.TrimEnd(Path.DirectorySeparatorChar).Length+1).Replace(Path.DirectorySeparatorChar,'/');if((exclude??"").Split(',').Select(x=>x.Trim().Trim('/')).Where(x=>x.Length>0).Any(x=>rel==x||rel.StartsWith(x+"/")))continue;CheckParents(p);if(Directory.Exists(p)){Walk(root,p,rows,exclude);continue;}Regular(p);var f=new FileInfo(p);long length=f.Length;DateTime modified=f.LastWriteTimeUtc;string key=p.Substring(root.TrimEnd(Path.DirectorySeparatorChar).Length+1).Replace(Path.DirectorySeparatorChar,'/');Local(root,key);string hash=Extras.HashFile(p);f.Refresh();if(f.Length!=length||f.LastWriteTimeUtc!=modified)throw new ClientError("File changed during scan");rows.Add(key,new OfflineFile{path=key,sha=hash,size=length});if(rows.Count>5000)throw new ClientError("Maximum 5000 files");}}
  public static string Decision(string b,string l,string r,bool write,bool delete){if(l==r)return "same";if(l==b)return r!=null?"get":(delete?"trash":"pending-delete");if(r==b){if(l==null)return write&&delete?"delete":(!write&&r!=null?"get":"pending-delete");return write?"put":"conflict";}return "conflict";}
  static string Hash(string p){CheckParents(p);if(File.Exists(p))Regular(p);return File.Exists(p)?Extras.HashFile(p):null;}
  static void Retain(string root,string path){string dest=Path.Combine(root,".hsm-recovery",Guid.NewGuid().ToString("N"),path.Substring(root.TrimEnd(Path.DirectorySeparatorChar).Length+1));CheckParents(dest);Directory.CreateDirectory(Path.GetDirectoryName(dest));File.Move(path,dest);}
  public static string Sync(Config c,OfflineFolder row){if(Interlocked.CompareExchange(ref running,1,0)!=0)throw new ClientError("Synchronization already running");try{Directory.CreateDirectory(Root);using(var syncLock=new FileStream(Path.Combine(Root,".sync-lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None))return Run(c,row);}finally{Interlocked.Exchange(ref running,0);}}
  static string Run(Config c,OfflineFolder row){
   if(row.wake)Protocol.Action(c,"access",CancellationToken.None).GetAwaiter().GetResult();
   var grant=(Call(c,"list").folders??new OfflineFolder[0]).FirstOrDefault(x=>x.id==row.id.Split('.')[0]);if(grant==null||row.write&&!grant.write)throw new ClientError("Folder permission revoked");
   string root=Path.GetFullPath(row.local);CheckParents(root);
   string scope;using(var m=new MemoryStream(Encoding.UTF8.GetBytes(c.SERVER_URL+"\0"+c.TOKEN+"\0"+row.id+"\0"+root)))scope=Extras.Hash(m);
   string state=Path.Combine(Root,scope+".json");var basis=File.Exists(state)?Json.Read<Dictionary<string,string>>(File.ReadAllBytes(state)):new Dictionary<string,string>();
   int failed=0;Post(c,"lease",row.id);
   using(var timer=new System.Threading.Timer(_=>{try{Post(c,"lease",row.id);}catch{Interlocked.Exchange(ref failed,1);}},null,30000,30000))try{
    var remote=(Call(c,"scan",row.id,"","",null,row.exclude??"").files??new OfflineFile[0]).ToDictionary(x=>x.path);var local=Scan(root,row.exclude);long cap=Math.Max(1,row.limit_gib)*1024L*1024*1024;
    if(remote.Values.Sum(x=>x.size)+local.Where(x=>!remote.ContainsKey(x.Key)).Sum(x=>x.Value.size)>cap)throw new ClientError("Offline storage limit exceeded");
    var excluded=(row.exclude??"").Split(',').Select(x=>x.Trim().Trim('/')).Where(x=>x.Length>0).ToArray();
    Func<string,bool> selected=n=>!excluded.Any(x=>n==x||n.StartsWith(x+"/",StringComparison.Ordinal));
    var conflicts=new List<string>();int changed=0;
    foreach(string name in basis.Keys.Union(local.Keys).Union(remote.Keys).OrderBy(x=>x).ToArray()){
     if(!selected(name))continue;if(failed!=0)throw new ClientError("Sleep blocker renewal failed");string b=basis.ContainsKey(name)?basis[name]:null,l=local.ContainsKey(name)?local[name].sha:null,r=remote.ContainsKey(name)?remote[name].sha:null;
     string action=Decision(b,l,r,row.write,row.delete),p=Local(root,name);
     if(action=="conflict"||action=="pending-delete"){conflicts.Add(name);continue;}
     if(action=="put"){if(Hash(p)!=l)throw new ClientError("Local file changed");using(var f=File.OpenRead(p)){var reply=Call(c,"put",row.id,name,r,f,"",l);if(reply.sha!=l)throw new ClientError("Upload confirmation mismatch");}r=l;changed++;}
     else if(action=="delete"){Post(c,"delete",row.id,name,r);r=null;changed++;}
     else if(action=="get"||action=="trash"){
      if(Hash(p)!=l)throw new ClientError("Local file changed");Directory.CreateDirectory(Path.GetDirectoryName(p));
      if(action=="get"){
       long size=remote[name].size;CheckParents(root);long used=Directory.GetFiles(root,"*",SearchOption.AllDirectories).Sum(x=>{CheckParents(x);return new FileInfo(x).Length;});
       if(used+size>cap||new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace<size+512L*1024*1024)throw new ClientError("Not enough local disk space");
       string tmp=Path.Combine(Path.GetDirectoryName(p),".hsm-part-"+Guid.NewGuid().ToString("N"));try{
        using(var response=Request(c,"get",row.id,name,r))using(var src=response.GetResponseStream())using(var dst=new FileStream(tmp,FileMode.CreateNew)){byte[] buf=new byte[1024*1024];long count=0;int n;while((n=src.Read(buf,0,buf.Length))>0){count+=n;if(count>size)throw new ClientError("Download too large");dst.Write(buf,0,n);}dst.Flush(true);}
        if(Extras.HashFile(tmp)!=r||Hash(p)!=l)throw new ClientError("File changed or checksum mismatch");if(File.Exists(p))Retain(root,p);File.Move(tmp,p);
       }finally{if(File.Exists(tmp))File.Delete(tmp);}
      }else if(File.Exists(p))Retain(root,p);changed++;
     }
     if(r==null)basis.Remove(name);else basis[name]=r;Atomic(state,Json.Write(basis));
    }
    return I18n.Tr("Abgleich beendet. Änderungen: ")+changed+I18n.Tr(" · Konflikte / ausstehende Löschungen: ")+conflicts.Count+"\n"+String.Join("\n",conflicts.Take(30));
   }finally{try{Post(c,"release",row.id);}catch{}}
  }
  public static OfflineFolder[] ConfigureMany(OfflineFolder[] grants,string[] selected,string destination){
   selected=selected.Distinct().ToArray();if(selected.Length==0)throw new ClientError(I18n.Tr("Mindestens einen Ordner anhaken."));
   var available=grants.ToDictionary(x=>x.id);if(selected.Any(x=>!available.ContainsKey(x)))throw new ClientError(I18n.Tr("Freigaben erneut laden."));
   string root=Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar);CheckParents(root);
   if(root==Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)||root.Length<3)throw new ClientError(I18n.Tr("Eigenen Unterordner auswählen."));
   var rows=Load().ToList();var planned=new List<OfflineFolder>();
   foreach(string id in selected){
    if(rows.Any(x=>x.id==id))continue;var grant=available[id];string slug=System.Text.RegularExpressions.Regex.Replace(grant.name??"Offline",@"[^\w.-]+","-").Trim('.','-');if(slug.Length==0)slug="Offline";if(slug.Length>60)slug=slug.Substring(0,60);
    string hash;using(var m=new MemoryStream(Encoding.UTF8.GetBytes(id)))hash=Extras.Hash(m).Substring(0,12);
    string target=Path.Combine(root,slug+"-"+hash);CheckParents(target);
    foreach(var row in rows.Concat(planned)){string old=Path.GetFullPath(row.local).TrimEnd(Path.DirectorySeparatorChar);if(target.Equals(old,StringComparison.OrdinalIgnoreCase)||target.StartsWith(old+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)||old.StartsWith(target+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new ClientError("Overlapping local folders");}
    if(Directory.Exists(target))Scan(target);planned.Add(new OfflineFolder{id=id,name=grant.name,local=target,limit_gib=10});
   }
   foreach(var row in planned){Directory.CreateDirectory(row.local);Scan(row.local);}rows.AddRange(planned);Save(rows.ToArray());return rows.Where(x=>selected.Contains(x.id)).ToArray();
  }
  public static string SyncMany(Config c,string[] selected){
   selected=selected.Distinct().ToArray();var rows=Load().ToDictionary(x=>x.id);if(selected.Length==0)throw new ClientError(I18n.Tr("Mindestens einen Ordner anhaken."));
   if(selected.Any(x=>!rows.ContainsKey(x)))throw new ClientError(I18n.Tr("Ausgewählte Ordner zuerst einrichten."));var results=new List<string>();
   if(Interlocked.CompareExchange(ref running,1,0)!=0)throw new ClientError(I18n.Tr("Synchronisierung läuft bereits."));
   try{Directory.CreateDirectory(Root);using(var syncLock=new FileStream(Path.Combine(Root,".sync-lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)){
    foreach(string id in selected){var row=rows[id];string result;try{result=Run(c,row);}catch(Exception ex){result=I18n.Tr("Fehler: ")+ex.Message;}results.Add((row.name??id)+"\n"+result);}
   }return String.Join("\n\n",results);}finally{Interlocked.Exchange(ref running,0);}
  }
  public static OfflineFolder Due(){foreach(var row in Load())if(row.interval>0&&(!last.ContainsKey(row.id)||DateTime.UtcNow-last[row.id]>=TimeSpan.FromMinutes(row.interval))){last[row.id]=DateTime.UtcNow;return row;}return null;}
 }
 public class OfflineForm:Form {
  Config config;CheckedListBox multiple=new CheckedListBox{Width=620,Height=130,CheckOnClick=true};FlowLayoutPanel box=new FlowLayoutPanel{Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown,WrapContents=false,AutoScroll=true};ComboBox folders=new ComboBox{Width=620,DropDownStyle=ComboBoxStyle.DropDownList};TextBox path=new TextBox{Width=620},exclude=new TextBox{Width=620};CheckBox write=new CheckBox{AutoSize=true,Text=I18n.Tr("Beide Richtungen synchronisieren")},delete=new CheckBox{AutoSize=true,Text=I18n.Tr("Löschungen übernehmen (mit Rückholablage)")},wake=new CheckBox{AutoSize=true,Text=I18n.Tr("Server vor dem Abgleich wecken")};NumericUpDown interval=new NumericUpDown{Maximum=1440},limit=new NumericUpDown{Minimum=1,Maximum=10000,Value=10};Label status=new Label{AutoSize=true,MaximumSize=new Size(630,0)};bool busy;
  public OfflineForm(Config c){config=c;Text=I18n.Tr("Offline-Dateien");Size=new Size(720,680);Controls.Add(box);Note(I18n.Tr("Freigegebene Serverordner als eigene lokale Kopie. Konflikte bleiben auf beiden Geräten erhalten und werden gemeldet. Kein Backup-Ersatz. Maximal 5000 Dateien; keine feste Dateigrößengrenze; keine Links oder leeren Ordner."));Note(I18n.Tr("Mehrere Ordner anhaken; darunter einen einzelnen Ordner bearbeiten."));box.Controls.Add(multiple);box.Controls.Add(folders);box.Controls.Add(path);box.Controls.Add(write);box.Controls.Add(delete);box.Controls.Add(wake);Note(I18n.Tr("Intervall in Minuten: 0 = nur manuell. Automatik läuft bei geöffnetem Client / Statussymbol."));box.Controls.Add(interval);Note(I18n.Tr("Lokales Speicherlimit einschließlich Rückholablage (GiB)"));box.Controls.Add(limit);Note(I18n.Tr("Ausschließen: relative Dateien / Ordner, durch Komma getrennt"));box.Controls.Add(exclude);
   folders.SelectedIndexChanged+=(s,e)=>{var grant=folders.SelectedItem as OfflineFolder;if(grant==null)return;var row=OfflineFiles.Load().FirstOrDefault(x=>x.id==grant.id)??new OfflineFolder{local=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"Offline-Dateien",SafeFolderId(grant.id))};path.Text=row.local;exclude.Text=row.exclude??"";write.Checked=row.write;write.Enabled=grant.write;delete.Checked=row.delete;wake.Checked=row.wake;interval.Value=row.interval;limit.Value=row.limit_gib;};
   Button(I18n.Tr("Freigaben laden"),()=>Work(()=>{var remote=OfflineFiles.Call(config,"list").folders??new OfflineFolder[0];var list=remote.Concat(OfflineFiles.Load().Where(x=>!remote.Any(y=>y.id==x.id))).ToArray();Invoke((Action)(()=>{var marked=multiple.CheckedItems.Cast<OfflineFolder>().Select(x=>x.id).ToArray();multiple.Items.Clear();foreach(var item in list)multiple.Items.Add(item,marked.Contains(item.id));folders.Items.Clear();folders.Items.AddRange(list);if(list.Length>0)folders.SelectedIndex=0;}));return I18n.Tr("Freigaben geladen.");}));
   Button(I18n.Tr("Server-Unterordner auswählen"),()=>{var grant=folders.SelectedItem as OfflineFolder;if(grant==null)return;using(var dialog=new OfflineBrowse(config,grant)){dialog.ShowDialog(this);foreach(var row in dialog.Selected){if(!folders.Items.Cast<OfflineFolder>().Any(x=>x.id==row.id)){folders.Items.Add(row);multiple.Items.Add(row,true);}}}});
   Button(I18n.Tr("Ausgewählte Ordner einrichten"),()=>{var ids=multiple.CheckedItems.Cast<OfflineFolder>().Select(x=>x.id).ToArray();using(var picker=new FolderBrowserDialog{Description=I18n.Tr("Gemeinsamen lokalen Basisordner auswählen")})if(picker.ShowDialog(this)==DialogResult.OK){OfflineFiles.ConfigureMany(multiple.Items.Cast<OfflineFolder>().ToArray(),ids,picker.SelectedPath);int at=folders.SelectedIndex;folders.SelectedIndex=-1;folders.SelectedIndex=at;status.Text=I18n.Tr("Ordner eingerichtet. Bestehende Einstellungen bleiben erhalten; neue Ordner starten nur lesend und manuell.");}});
   Button(I18n.Tr("Ausgewählte Ordner synchronisieren"),()=>{var ids=multiple.CheckedItems.Cast<OfflineFolder>().Select(x=>x.id).ToArray();Work(()=>OfflineFiles.SyncMany(config,ids));});
   Button(I18n.Tr("Ordner auswählen"),()=>{using(var d=new FolderBrowserDialog())if(d.ShowDialog(this)==DialogResult.OK)path.Text=d.SelectedPath;});
   Button(I18n.Tr("Speichern"),()=>{Save();status.Text=I18n.Tr("Gespeichert.");});
   Button(I18n.Tr("Jetzt synchronisieren"),()=>{var row=Save();Work(()=>OfflineFiles.Sync(config,row));});
   Button(I18n.Tr("Abgleich entfernen"),()=>{var row=folders.SelectedItem as OfflineFolder;if(row!=null&&MessageBox.Show(this,I18n.Tr("Abgleich entfernen? Lokale Dateien bleiben erhalten."),Text,MessageBoxButtons.OKCancel)==DialogResult.OK)OfflineFiles.Save(OfflineFiles.Load().Where(x=>x.id!=row.id).ToArray());});box.Controls.Add(status);folders.Items.AddRange(OfflineFiles.Load());multiple.Items.AddRange(OfflineFiles.Load());if(folders.Items.Count>0)folders.SelectedIndex=0;FormClosing+=(s,e)=>{if(busy)e.Cancel=true;};
  }
  static string SafeFolderId(string id){using(var stream=new MemoryStream(Encoding.UTF8.GetBytes(id)))return Extras.Hash(stream).Substring(0,16);}
  void Note(string s){box.Controls.Add(new Label{Text=s,AutoSize=true,MaximumSize=new Size(630,0)});}void Button(string s,Action run){var b=new Button{Text=s,AutoSize=true};b.Click+=(a,e)=>{if(!busy)try{run();}catch(Exception x){status.Text=x.Message;}};box.Controls.Add(b);}
  async void Work(Func<string> run){busy=true;try{status.Text=await Task.Run(run);}catch(Exception e){status.Text=e.Message;}finally{busy=false;}}
  OfflineFolder Save(){var grant=folders.SelectedItem as OfflineFolder;if(grant==null)throw new ClientError("Choose a folder first");string local=Path.GetFullPath(path.Text).TrimEnd(Path.DirectorySeparatorChar);if(local==Path.GetPathRoot(local).TrimEnd(Path.DirectorySeparatorChar)||local==Environment.GetFolderPath(Environment.SpecialFolder.UserProfile))throw new ClientError("Choose a dedicated subfolder");foreach(var r in OfflineFiles.Load().Where(x=>x.id!=grant.id))if(local.Equals(r.local,StringComparison.OrdinalIgnoreCase)||local.StartsWith(r.local+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)||r.local.StartsWith(local+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new ClientError("Overlapping local folders");Directory.CreateDirectory(local);OfflineFiles.Scan(local,exclude.Text);var row=new OfflineFolder{id=grant.id,name=grant.name,local=local,write=write.Checked&&grant.write,delete=delete.Checked,wake=wake.Checked,interval=(int)interval.Value,limit_gib=(int)limit.Value,exclude=exclude.Text};OfflineFiles.Save(OfflineFiles.Load().Where(x=>x.id!=row.id).Concat(new[]{row}).ToArray());return row;}
 }
 public class OfflineBrowse:Form {
  public List<OfflineFolder> Selected=new List<OfflineFolder>();Config config;OfflineFolder root;OfflineReply state;bool busy;
  Label label=new Label{AutoSize=true,MaximumSize=new Size(540,0)};ListBox list=new ListBox{Width=540,Height=230};
  public OfflineBrowse(Config c,OfflineFolder grant){config=c;root=grant;Text=I18n.Tr("Server-Unterordner auswählen");Size=new Size(600,460);var box=new FlowLayoutPanel{Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown};Controls.Add(box);box.Controls.Add(label);box.Controls.Add(list);
   Action<string,Action> button=(title,action)=>{var b=new Button{Text=I18n.Tr(title),AutoSize=true};b.Click+=(s,e)=>{if(!busy)action();};box.Controls.Add(b);};
   button("Öffnen",()=>{var row=list.SelectedItem as OfflineFolder;if(row!=null)LoadFolder(row.id);});button("Eine Ebene höher",()=>{if(state!=null&&!String.IsNullOrEmpty(state.parent))LoadFolder(state.parent);});
   button("Diesen Ordner zur Auswahl hinzufügen",()=>{if(state!=null&&!Selected.Any(x=>x.id==state.current))Selected.Add(new OfflineFolder{id=state.current,name=String.IsNullOrEmpty(state.current_name)?root.name:state.current_name,write=root.write});});
   Shown+=(s,e)=>LoadFolder(root.id);FormClosing+=(s,e)=>{if(busy)e.Cancel=true;};
  }
  async void LoadFolder(string id){busy=true;try{var data=await Task.Run(()=>OfflineFiles.Call(config,"browse",id));state=data;label.Text=String.IsNullOrEmpty(data.current_name)?root.name:data.current_name;list.Items.Clear();list.Items.AddRange(data.folders??new OfflineFolder[0]);if(list.Items.Count>0)list.SelectedIndex=0;}catch(Exception e){label.Text=e.Message;}finally{busy=false;}}
 }

}
