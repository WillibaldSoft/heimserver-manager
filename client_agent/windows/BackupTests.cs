// SPDX-License-Identifier: GPL-3.0-or-later
using System;using System.IO;using HeimserverClient;
class BackupTests {
 static int Main(string[] args){
  string root=Path.Combine(Path.GetTempPath(),"hsm-test-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
  try{
   string source=Path.Combine(root,"source");Directory.CreateDirectory(source);Directory.CreateDirectory(Path.Combine(source,"empty"));File.WriteAllText(Path.Combine(source,"test.txt"),"Backup äöü");
   var random=new byte[5*1024*1024];new Random(42).NextBytes(random);File.WriteAllBytes(Path.Combine(source,"large.bin"),random);
   var c=new Config{SERVER_URL=args[0],TOKEN="test-token",CLIENT_NAME="Test"};
   Console.WriteLine(Extras.Backup(c,source,s=>{}));var rows=Extras.Call(c,"list").backups;if(rows.Length!=1)throw new Exception("List");
   string dest=Path.Combine(root,"restored");Extras.Restore(c,rows[0],dest,s=>{});
   if(File.ReadAllText(Path.Combine(dest,"test.txt"))!="Backup äöü"||!Directory.Exists(Path.Combine(dest,"empty")))throw new Exception("Restore content");
   if(Extras.HashFile(Path.Combine(source,"large.bin"))!=Extras.HashFile(Path.Combine(dest,"large.bin")))throw new Exception("Large file mismatch");
   bool refused=false;try{Extras.Restore(c,rows[0],dest,s=>{});}catch(ClientError){refused=true;}if(!refused)throw new Exception("Overwrite allowed");
   rows[0].sha256=new string('0',64);refused=false;try{Extras.Restore(c,rows[0],Path.Combine(root,"bad"),s=>{});}catch(ClientError){refused=true;}if(!refused||Directory.Exists(Path.Combine(root,"bad")))throw new Exception("Hash check failed");
   foreach(string kind in new[]{"traversal","backslash","reserved"}){
    var bad=Extras.Call(c,"malicious",null,"&kind="+kind).backups[0];refused=false;
    try{Extras.Restore(c,bad,Path.Combine(root,"bad-"+kind),s=>{});}catch(ClientError){refused=true;}
    if(!refused||Directory.Exists(Path.Combine(root,"bad-"+kind)))throw new Exception("Unsafe ZIP accepted: "+kind);
   }
   Console.WriteLine("Windows: ZIP roundtrip, empty folders, overwrite and checksum guards OK");return 0;
  }catch(Exception e){Console.Error.WriteLine(e);return 1;}finally{Directory.Delete(root,true);}
 }
}
