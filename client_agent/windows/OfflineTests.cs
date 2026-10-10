using System;using System.IO;using HeimserverClient;
class OfflineTests {
 static void Equal(string a,string b){if(a!=b)throw new Exception(a+" != "+b);}
 static void Main(){
  Equal("get",OfflineFiles.Decision(null,null,"r",true,false));Equal("put",OfflineFiles.Decision("b","l","b",true,false));Equal("conflict",OfflineFiles.Decision("b","l","r",true,true));Equal("pending-delete",OfflineFiles.Decision("b",null,"b",true,false));Equal("delete",OfflineFiles.Decision("b",null,"b",true,true));Equal("trash",OfflineFiles.Decision("b","b",null,true,true));
  string dir=Path.Combine(Path.GetTempPath(),Guid.NewGuid().ToString("N"));Directory.CreateDirectory(dir);
  try{File.WriteAllText(Path.Combine(dir,"a"),"test");if(OfflineFiles.Scan(dir).Count!=1)throw new Exception("scan");if(OfflineFiles.Scan(dir,"a").Count!=0)throw new Exception("exclude");foreach(string path in new[]{"../a",".hsm-part-a","/a"}){bool rejected=false;try{OfflineFiles.Local(dir,path);}catch(ClientError){rejected=true;}if(!rejected)throw new Exception("path accepted");}var data=new System.Collections.Generic.Dictionary<string,string>{{"a","b"}};OfflineFiles.Atomic(Path.Combine(dir,"state"),Json.Write(data));OfflineFiles.Atomic(Path.Combine(dir,"state"),Json.Write(data));Equal("b",Json.Read<System.Collections.Generic.Dictionary<string,string>>(File.ReadAllBytes(Path.Combine(dir,"state")))["a"]);}finally{Directory.Delete(dir,true);}
  string batch=Path.Combine(Path.GetTempPath(),Guid.NewGuid().ToString("N"));Directory.CreateDirectory(batch);string previousRoot=OfflineFiles.Root;
  try{
   OfflineFiles.Root=Path.Combine(batch,"config");var old=new OfflineFolder{id="a",name="A",local=Path.Combine(batch,"old"),write=true,interval=15,limit_gib=25};OfflineFiles.Save(new[]{old});
   var grants=new[]{new OfflineFolder{id="a",name="Docs",write=true},new OfflineFolder{id="b",name="Docs",write=true},new OfflineFolder{id="c",name="Docs",write=true}};
   var rows=OfflineFiles.ConfigureMany(grants,new[]{"a","b","c"},Path.Combine(batch,"offline"));if(rows.Length!=3||!rows[0].write||rows[0].interval!=15||rows[1].write||rows[1].interval!=0||rows[1].local==rows[2].local)throw new Exception("batch setup");
   var second=OfflineFiles.ConfigureMany(grants,new[]{"b","c"},Path.Combine(batch,"other"));Equal(rows[1].local,second[0].local);
   bool denied=false;try{OfflineFiles.ConfigureMany(new[]{new OfflineFolder{id="d",name="D"}},new[]{"d"},Path.Combine(old.local,"nested"));}catch(ClientError){denied=true;}if(!denied||OfflineFiles.Load().Length!=3)throw new Exception("overlap changed configuration");
  }finally{OfflineFiles.Root=previousRoot;Directory.Delete(batch,true);}
  Console.WriteLine("Offline Windows decisions, path validation, scan, exclusions and atomic state: OK");
 }
}
