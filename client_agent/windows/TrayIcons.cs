// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.Drawing;
using System.Reflection;
using System.Runtime.InteropServices;
namespace HeimserverClient {
    sealed class TrayIcons : IDisposable {
        public readonly Icon Offline = Load("offline"), Connecting = Load("connecting"), Online = Load("online");
        [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr handle);
        static Icon Load(string name) {
            using(var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("hsm."+name+".png"))
            using(var source=new Bitmap(stream))
            using(var small=new Bitmap(source,new Size(32,32))) {
                IntPtr handle=small.GetHicon();
                try { using(var icon=Icon.FromHandle(handle)) return (Icon)icon.Clone(); }
                finally { if(Environment.OSVersion.Platform==PlatformID.Win32NT) DestroyIcon(handle); }
            }
        }
        public void Dispose(){Offline.Dispose();Connecting.Dispose();Online.Dispose();}
    }
}
