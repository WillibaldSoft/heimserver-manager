// SPDX-License-Identifier: GPL-3.0-or-later
using System;
using System.Globalization;
using System.Threading;
using HeimserverClient;
class I18nTests {
    static void Check(bool ok) { if(!ok) throw new Exception("Language regression"); }
    static int Main() {
        foreach(string locale in new[]{"de-DE","de-AT","de-CH","en-US","fr-FR"}) {
            Thread.CurrentThread.CurrentUICulture = new CultureInfo(locale);
            bool german = locale.StartsWith("de-");
            Check(I18n.Language(CultureInfo.CurrentUICulture) == (german?"de":"en"));
            Check(I18n.Tr("Speichern") == (german?"Speichern":"Save"));
            Check(I18n.Tr("Client-Eigenname") == "Client-Eigenname");
            Check(I18n.Tr("with_server") == "with_server");
            var c=new Config{SERVER_URL="https://server.example",TOKEN="test-token",CLIENT_NAME="Client-Eigenname",CLIENT_MODE="with_server"};
            Check(c.Validate().CLIENT_MODE == "with_server");
            Check(c.Validate().CLIENT_NAME == "Client-Eigenname");
        }
        Check(I18n.Language(CultureInfo.InvariantCulture)=="en");
        Console.WriteLine("Language selection and unchanged configuration: OK"); return 0;
    }
}
